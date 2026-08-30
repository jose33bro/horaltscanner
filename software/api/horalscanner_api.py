"""HoralScanner Flask API."""

from __future__ import annotations

import logging
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

# Add repo root to path so 'software' module can be imported
_API_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _API_DIR.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from software.api import config_manager
from software.api.camera_driver import LogitechCamera, PiCamera, analyze_camera_frame, analyze_laser_line
from software.api.calibration_pose import PoseMemory, get_default_pose, move_to_pose, read_lidar_distance
from software.api.lidar_driver import LidarDriver
from software.api.scanner_engine import ReconstructionEngine, ScanSession

logger = logging.getLogger(__name__)

try:
    from software.drivers.stm32_driver import STM32Driver
except Exception as exc:  # pragma: no cover - environment dependent
    STM32Driver = None  # type: ignore[assignment]
    logger.warning("STM32Driver import failed: %s", exc)

try:
    from software.drivers.gpio_driver import GPIODriver
except Exception as exc:  # pragma: no cover - environment dependent
    GPIODriver = None  # type: ignore[assignment]
    logger.warning("GPIODriver import failed: %s", exc)


app = Flask(__name__)

_WEB_DIR = _API_DIR.parent / "web"
_VERSION_FILE = _REPO_ROOT / "VERSION"
_VERSION = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else "unknown"


@app.after_request
def _add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/", methods=["GET"])
def index():
    return send_from_directory(str(_WEB_DIR), "index.html")


@app.route("/app.js", methods=["GET"])
def web_app_script():
    return send_from_directory(str(_WEB_DIR), "app.js")


@app.route("/style.css", methods=["GET"])
def web_styles():
    return send_from_directory(str(_WEB_DIR), "style.css")


@app.route("/viewer3d.js", methods=["GET"])
def web_3d_viewer_script():
    return send_from_directory(str(_WEB_DIR), "viewer3d.js")


def _initialize_driver(driver: Any, name: str) -> None:
    """Attempt to connect a driver without aborting startup."""
    if driver is None:
        logger.warning("%s not available", name)
        return

    try:
        if not driver.connect():
            logger.warning("%s connection failed", name)
    except Exception as exc:  # pragma: no cover - hardware dependent
        logger.warning("%s connection error: %s", name, exc)


hardware_config = config_manager.load_hardware_config()
application_config = config_manager.load()
pi_gpio_enabled = bool(hardware_config.get("hardware", {}).get("pi_gpio", False))
stm32_enabled = bool(hardware_config.get("hardware", {}).get("mcu"))
serial_config = hardware_config.get("serial", {})
camera_config = hardware_config.get("cameras", {})
scanner_config = application_config.get("scanner", {})

stm32_driver = (
    STM32Driver(simulation=not stm32_enabled, hardware_config=hardware_config)
    if STM32Driver
    else None
)
gpio_driver = (
    GPIODriver(simulation=not pi_gpio_enabled, hardware_config=hardware_config)
    if GPIODriver
    else None
)
lidar_driver = LidarDriver(
    port=serial_config.get("lidar_port", "/dev/ttyUSB0"),
    baud=int(serial_config.get("lidar_baud", 115200)),
)
pi_camera = PiCamera()
usb_camera = LogitechCamera(device_id=int(camera_config.get("usb_device_id", 0)))
scan_session = ScanSession(simulation=bool(scanner_config.get("simulation", False)))
reconstruction_engine = ReconstructionEngine(scan_session)
pose_memory = PoseMemory()

_initialize_driver(stm32_driver, "STM32Driver")
_initialize_driver(gpio_driver, "GPIODriver")


def _get_camera(camera_name: str):
    cameras = {
        "pi": pi_camera,
        "usb": usb_camera,
    }
    return cameras.get(camera_name)


def _ensure_camera_open(camera) -> bool:
    return camera.is_open or camera.open()


def _ensure_lidar_connected() -> bool:
    return lidar_driver.connected or lidar_driver.connect()


def _json_error(message: str, status_code: int = 400):
    return jsonify({"success": False, "error": message}), status_code


def _parse_pwm_speed(data: dict[str, Any]) -> float:
    """Parse PWM speed from request payload.

    Accepts either:
      - speed/pwm in 0.0-1.0 range
      - percent in 0-100 range
    """
    if "speed" in data:
        speed = float(data["speed"])
        if speed < 0 or speed > 1.0:
            raise ValueError("Speed must be in 0.0-1.0")
        return speed

    if "pwm" in data:
        speed = float(data["pwm"])
        if speed < 0 or speed > 1.0:
            raise ValueError("PWM must be in 0.0-1.0")
        return speed

    if "percent" in data:
        percent = float(data["percent"])
        if percent < 0 or percent > 100.0:
            raise ValueError("Percent must be in 0-100")
        return percent / 100.0

    raise ValueError("Missing speed value")


@app.route("/api/laser/<side>", methods=["POST"])
def laser(side: str):
    data = request.get_json(silent=True) or {}
    state = bool(data.get("state", False))

    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)

    try:
        success = gpio_driver.laser_on(side) if state else gpio_driver.laser_off(side)
        if not success:
            return _json_error("Failed to update laser state")

        return jsonify({"success": True, "status": gpio_driver.get_laser_status()})
    except Exception:
        logger.exception("Laser route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/led/color", methods=["POST"])
def led_color():
    data = request.get_json(silent=True) or {}
    try:
        r = int(data.get("r", 0))
        g = int(data.get("g", 0))
        b = int(data.get("b", 0))
    except (TypeError, ValueError):
        return _json_error("Invalid LED color values", 400)

    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)

    try:
        success = gpio_driver.led_set(r, g, b)
        if not success:
            return _json_error("Failed to set LED color")

        return jsonify({"success": True, "status": gpio_driver.get_led_status()})
    except Exception:
        logger.exception("LED route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/move/<axis>", methods=["POST"])
def move(axis: str):
    data = request.get_json(silent=True) or {}
    try:
        distance = float(data.get("mm", 0.0))
    except (TypeError, ValueError):
        return _json_error("Invalid distance value", 400)

    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        success = stm32_driver.move_motor(axis, distance)
        if not success:
            return _json_error("Failed to move motor")

        return jsonify({"success": True, "status": stm32_driver.get_motor_status()})
    except Exception:
        logger.exception("Move route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/home/<target>", methods=["POST"])
def home(target: str):
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        success = stm32_driver.home_motor(target)
        if not success:
            return _json_error("Failed to home motor")

        return jsonify({"success": True, "status": stm32_driver.get_motor_status()})
    except Exception:
        logger.exception("Home route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/motor/status", methods=["GET", "POST"])
def motor_status():
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        return jsonify({"success": True, "status": stm32_driver.get_motor_status()})
    except Exception:
        logger.exception("Motor status route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/motor/stop", methods=["POST"])
def motor_stop():
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    data = request.get_json(silent=True) or {}
    axis = str(data.get("axis", "all"))

    try:
        success = stm32_driver.stop_motor(axis)
        if not success:
            return _json_error("Failed to stop motor")

        return jsonify({"success": True, "status": stm32_driver.get_motor_status()})
    except Exception:
        logger.exception("Motor stop route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/fan/pi", methods=["POST"])
def fan_pi():
    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)

    data = request.get_json(silent=True) or {}
    try:
        speed = _parse_pwm_speed(data)
    except (TypeError, ValueError):
        return _json_error("Invalid fan speed value", 400)

    try:
        success = gpio_driver.set_fan_speed(speed)
        if not success:
            return _json_error("Failed to set Pi fan speed", 502)
        return jsonify({"success": True, "status": gpio_driver.get_fan_status()})
    except Exception:
        logger.exception("Pi fan route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/fan/creality", methods=["POST"])
def fan_creality():
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    data = request.get_json(silent=True) or {}
    try:
        speed = _parse_pwm_speed(data)
    except (TypeError, ValueError):
        return _json_error("Invalid fan speed value", 400)

    try:
        success = stm32_driver.set_fan_speed("creality", speed)
        if not success:
            return _json_error("Failed to set Creality fan speed", 502)
        return jsonify({"success": True, "status": stm32_driver.get_fan_status()})
    except Exception:
        logger.exception("Creality fan route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/fan/temperature", methods=["POST"])
def fan_temperature():
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    data = request.get_json(silent=True) or {}
    try:
        speed = _parse_pwm_speed(data)
    except (TypeError, ValueError):
        return _json_error("Invalid fan speed value", 400)

    try:
        success = stm32_driver.set_fan_speed("temperature", speed)
        if not success:
            return _json_error("Failed to set temperature fan speed", 502)
        return jsonify({"success": True, "status": stm32_driver.get_fan_status()})
    except Exception:
        logger.exception("Temperature fan route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/fan/status", methods=["GET"])
def fan_status():
    if gpio_driver is None and stm32_driver is None:
        return _json_error("No fan drivers available", 503)

    try:
        status: dict[str, Any] = {}
        if gpio_driver is not None:
            status["pi"] = gpio_driver.get_fan_status()
        if stm32_driver is not None:
            status.update(stm32_driver.get_fan_status())
        return jsonify({"success": True, "status": status})
    except Exception:
        logger.exception("Fan status route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/temperature/board", methods=["GET"])
def temperature_board():
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        temperature = stm32_driver.read_board_temperature()
        if temperature is None:
            return _json_error("Failed to read board temperature", 502)
        return jsonify({"success": True, "status": {"board_c": temperature}})
    except Exception:
        logger.exception("Board temperature route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/temperature/all", methods=["GET"])
def temperature_all():
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        board_temperature = stm32_driver.read_board_temperature()
        if board_temperature is None:
            return _json_error("Failed to read board temperature", 502)
        status = {
            "board_c": board_temperature,
            "sensor_pin": "PC5",
            "sensor_type": "EPCOS 100K B57560G104F",
        }
        return jsonify({"success": True, "status": status})
    except Exception:
        logger.exception("All temperature route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/laser/status", methods=["GET"])
def laser_status():
    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)
    try:
        return jsonify({"success": True, "status": gpio_driver.get_laser_status()})
    except Exception:
        logger.exception("Laser status route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/led/status", methods=["GET"])
def led_status():
    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)
    try:
        return jsonify({"success": True, "status": gpio_driver.get_led_status()})
    except Exception:
        logger.exception("LED status route failed")
        return _json_error("Internal server error", 500)


@app.route("/api/lidar/read", methods=["POST"])
def lidar_read():
    if not _ensure_lidar_connected():
        return _json_error("TF-Luna unavailable", 503)
    distance = lidar_driver.read_distance_mm()
    if distance is None:
        return _json_error("TF-Luna measurement failed", 502)
    return jsonify({
        "success": True,
        "distance_mm": round(distance, 1),
        "offset_mm": lidar_driver.get_offset(),
    })


@app.route("/api/lidar/calibrate", methods=["POST"])
def lidar_calibrate():
    data = request.get_json(silent=True) or {}
    try:
        known_distance_mm = float(data.get("known_distance_mm", 300.0))
        if known_distance_mm <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _json_error("Known distance must be positive", 400)
    if not _ensure_lidar_connected():
        return _json_error("TF-Luna unavailable", 503)
    offset = lidar_driver.calibrate(known_distance_mm=known_distance_mm)
    if offset is None:
        return _json_error("TF-Luna calibration failed: no measurements", 502)
    return jsonify({"success": True, "offset_mm": round(offset, 1)})


@app.route("/api/camera/<camera_name>/frame", methods=["GET"])
def camera_frame(camera_name: str):
    camera = _get_camera(camera_name)
    if camera is None:
        return _json_error("Unknown camera", 404)
    if not _ensure_camera_open(camera):
        return _json_error("Camera unavailable", 503)
    jpeg = camera.capture_jpeg()
    if jpeg is None:
        return _json_error("Camera capture failed", 502)
    return Response(jpeg, mimetype="image/jpeg")


@app.route("/api/camera/<camera_name>/status", methods=["GET"])
def camera_status(camera_name: str):
    camera = _get_camera(camera_name)
    if camera is None:
        return _json_error("Unknown camera", 404)
    available = _ensure_camera_open(camera)
    return jsonify({
        "success": True,
        "camera": camera_name,
        "available": available,
    })


@app.route("/api/camera/<camera_name>/test", methods=["POST"])
def camera_test(camera_name: str):
    camera = _get_camera(camera_name)
    if camera is None:
        return _json_error("Unknown camera", 404)
    if not _ensure_camera_open(camera):
        return _json_error("Camera unavailable", 503)
    jpeg = camera.capture_jpeg()
    if jpeg is None:
        return _json_error("Camera capture failed", 502)
    result = analyze_camera_frame(jpeg)
    if not result["analysis_available"]:
        return _json_error("OpenCV camera analysis unavailable", 503)
    return jsonify({"success": True, "camera": camera_name, "result": result})


# ---------------------------------------------------------------------------
# Camera calibration pose endpoints
# ---------------------------------------------------------------------------

@app.route("/api/camera/<camera_name>/goto_calibration_pose", methods=["POST"])
def camera_goto_calibration_pose(camera_name: str):
    """Move motors to the default calibration pose for *camera_name*.

    Pi Camera  → moves X and Y only (Z is never touched).
    Logitech   → moves X, Y, and Z.

    After positioning, reads the TF-Luna distance when available.

    Returns JSON:
      - camera: camera name
      - pose: target axes and their positions (mm)
      - moved_axes: axes that were successfully moved
      - lidar_distance_mm: measured distance or null
      - instruction: French status message
    """
    if camera_name not in ("pi", "usb"):
        return _json_error("Caméra inconnue ; utilisez 'pi' ou 'usb'", 404)

    if stm32_driver is None:
        return _json_error("Contrôleur moteur non disponible", 503)

    pose = get_default_pose(camera_name)
    if pose is None:
        return _json_error("Pose de calibration introuvable", 500)

    try:
        moved = move_to_pose(stm32_driver, pose)
    except (ConnectionError, RuntimeError) as exc:
        logger.error("goto_calibration_pose failed: %s", exc)
        return _json_error(f"Déplacement moteur échoué : {exc}", 503)

    lidar_dist = read_lidar_distance(lidar_driver)

    camera_label = "Pi Camera" if camera_name == "pi" else "Caméra USB Logitech"
    instruction = f"Pose de calibration {camera_label} atteinte."
    if lidar_dist is not None:
        instruction += f" Distance TF-Luna : {lidar_dist:.1f} mm."

    return jsonify({
        "success": True,
        "camera": camera_name,
        "pose": pose,
        "moved_axes": moved,
        "lidar_distance_mm": lidar_dist,
        "instruction": instruction,
    })


@app.route("/api/camera/<camera_name>/save_scan_pose", methods=["POST"])
def camera_save_scan_pose(camera_name: str):
    """Save the current motor position as the scan pose for *camera_name*.

    The saved pose is used to return the machine to the correct position
    before starting a scan.

    Returns JSON:
      - camera: camera name
      - saved_pose: the pose that was saved
    """
    if camera_name not in ("pi", "usb"):
        return _json_error("Caméra inconnue ; utilisez 'pi' ou 'usb'", 404)

    if stm32_driver is None:
        return _json_error("Contrôleur moteur non disponible", 503)

    status = stm32_driver.get_motor_status()
    positions = status.get("positions", {})

    # For Pi Camera keep only X/Y; for Logitech keep X/Y/Z
    if camera_name == "pi":
        saved = {k: v for k, v in positions.items() if k in ("x", "y")}
    else:
        saved = {k: v for k, v in positions.items() if k in ("x", "y", "z")}

    pose_memory.save_pose(camera_name, saved)

    camera_label = "Pi Camera" if camera_name == "pi" else "Caméra USB Logitech"
    return jsonify({
        "success": True,
        "camera": camera_name,
        "saved_pose": saved,
        "instruction": f"Pose de scan {camera_label} mémorisée.",
    })


@app.route("/api/camera/<camera_name>/goto_scan_pose", methods=["POST"])
def camera_goto_scan_pose(camera_name: str):
    """Return the machine to the previously saved scan pose for *camera_name*.

    Returns JSON:
      - camera: camera name
      - pose: restored axes and positions (mm)
      - moved_axes: axes that were successfully moved
      - lidar_distance_mm: measured distance or null
      - instruction: French status message
    """
    if camera_name not in ("pi", "usb"):
        return _json_error("Caméra inconnue ; utilisez 'pi' ou 'usb'", 404)

    if stm32_driver is None:
        return _json_error("Contrôleur moteur non disponible", 503)

    saved = pose_memory.get_pose(camera_name)
    if saved is None:
        return _json_error("Aucune pose de scan mémorisée pour cette caméra", 404)

    try:
        moved = move_to_pose(stm32_driver, saved)
    except (ConnectionError, RuntimeError) as exc:
        logger.error("goto_scan_pose failed: %s", exc)
        return _json_error(f"Déplacement moteur échoué : {exc}", 503)

    lidar_dist = read_lidar_distance(lidar_driver)

    camera_label = "Pi Camera" if camera_name == "pi" else "Caméra USB Logitech"
    instruction = f"Retour à la pose de scan {camera_label}."
    if lidar_dist is not None:
        instruction += f" Distance TF-Luna : {lidar_dist:.1f} mm."

    return jsonify({
        "success": True,
        "camera": camera_name,
        "pose": saved,
        "moved_axes": moved,
        "lidar_distance_mm": lidar_dist,
        "instruction": instruction,
    })


@app.route("/api/camera/scan_poses", methods=["GET"])
def camera_scan_poses():
    """Return all saved scan poses.

    Returns JSON:
      - poses: dict keyed by camera name
    """
    return jsonify({"success": True, "poses": pose_memory.all_poses()})


@app.route("/api/laser/align/<side>", methods=["POST"])
def laser_align(side: str):
    """Automatic laser alignment check using the Pi Camera.

    Turns on the requested laser (left or right), captures a Pi Camera frame,
    analyses the laser line orientation, then turns the laser back off.

    Returns JSON:
      - side: which laser was tested
      - line_detected: whether a laser line was found in the image
      - angle_deg: measured angle from vertical (0 = perfectly vertical)
      - correction_deg: signed correction to apply (negative = rotate left,
                        positive = rotate right)
      - instruction: human-readable guidance in French
    """
    if side not in ("left", "right"):
        return _json_error("Invalid side; use 'left' or 'right'", 400)

    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)

    if not _ensure_camera_open(pi_camera):
        return _json_error("Pi Camera unavailable", 503)

    side_label = "gauche" if side == "left" else "droit"

    try:
        # Turn off both lasers, then enable only the requested one
        gpio_driver.laser_off("left")
        gpio_driver.laser_off("right")
        gpio_driver.laser_on(side)

        jpeg = pi_camera.capture_jpeg()

        gpio_driver.laser_off(side)
    except Exception:
        # Best-effort cleanup
        try:
            gpio_driver.laser_off(side)
        except Exception:
            pass
        logger.exception("Laser align route failed")
        return _json_error("Internal server error", 500)

    if jpeg is None:
        return _json_error("Pi Camera capture failed", 503)

    result = analyze_laser_line(jpeg)
    if not result.get("analysis_available", False):
        return _json_error("OpenCV laser analysis unavailable", 503)

    return jsonify({
        "success": True,
        "side": side,
        "side_label": side_label,
        "line_detected": result.get("line_detected", False),
        "angle_deg": result.get("angle_deg"),
        "correction_deg": result.get("correction_deg"),
        "instruction": f"Laser {side_label}: {result.get('instruction', '')}",
    })


@app.route("/api/scan/start", methods=["POST"])
def scan_start():
    try:
        scan_session.start()
    except RuntimeError as exc:
        return _json_error(str(exc), 503)
    return jsonify({"success": True, "status": scan_session.status()})


@app.route("/api/scan/stop", methods=["POST"])
def scan_stop():
    scan_session.stop()
    return jsonify({"success": True, "status": scan_session.status()})


@app.route("/api/scan/status", methods=["GET"])
def scan_status():
    return jsonify({"success": True, "status": scan_session.status()})


@app.route("/api/scan/pointcloud", methods=["GET"])
def scan_pointcloud():
    return jsonify({"success": True, **scan_session.get_pointcloud()})


@app.route("/api/model/reconstruct", methods=["POST"])
def model_reconstruct():
    result = reconstruction_engine.reconstruct()
    status_code = 200 if result["ok"] else 409
    return jsonify({"success": result["ok"], **result}), status_code


@app.route("/api/model/current", methods=["GET"])
def model_current():
    model_format = request.args.get("format", "stl").lower()
    if model_format not in {"stl", "amf"}:
        return _json_error("Format must be stl or amf", 400)
    model = reconstruction_engine.get_model(model_format)
    if model is None:
        return _json_error("No reconstructed model available", 404)
    return send_file(
        BytesIO(model),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=f"horalscanner-model.{model_format}",
    )


@app.route("/api/status", methods=["GET"])
def api_status():
    gpio_ready = bool(
        gpio_driver is not None
        and (
            getattr(gpio_driver, "simulation", True)
            or getattr(gpio_driver, "hardware_available", False)
        )
    )
    stm32_ready = bool(
        stm32_driver is not None
        and getattr(stm32_driver, "connected", True)
    )
    return jsonify({
        "success": True,
        "status": {
            "api": "ok",
            "gpio_driver": gpio_ready,
            "stm32_driver": stm32_ready,
            "version": _VERSION,
        },
    })



@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=5000, debug=False)
