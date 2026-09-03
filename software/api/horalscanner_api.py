"""HoralScanner Flask API (modern version)."""

from __future__ import annotations

import copy
import json
import logging
import math
import sys
import threading
import time
from functools import wraps
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

# Add repo root to path so 'software' module can be imported
_API_DIR = Path(__file__).resolve().parent
_SOFTWARE_DIR = _API_DIR.parent
_REPO_ROOT = _API_DIR.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_SOFTWARE_DIR))

# Modern Flask imports
from flask import (
    Blueprint,
    Flask,
    Response,
    g,
    has_request_context,
    jsonify,
    request,
    send_file,
    send_from_directory,
)

# Blueprint moderne
api_bp = Blueprint("api", __name__)

# Modern API imports
try:
    from . import config_manager
except ImportError:  # pragma: no cover - direct script execution
    from software.api import config_manager
from software.api.camera_calibration import (
    get_all_saved_poses,
    get_calibration_pose,
    get_saved_pose,
    move_to_calibration_pose,
    restore_scan_pose,
    save_current_pose,
)
from software.api.camera_driver import (
    LogitechCamera,
    PiCamera,
    analyze_camera_frame,
    analyze_laser_line,
)
from software.api.calibration_pose import (
    PoseMemory,
    get_default_pose,
    move_to_pose,
    read_lidar_distance,
)
from software.api.lidar_driver import LidarDriver
from software.api.hardware_lock import HardwareReservationLock
from software.api.geometric_calibration import (
    AtomicCalibrationStore,
    CalibrationError,
    GeometricCalibrationService,
)
from software.api.scanner_engine import (
    ReconstructionEngine,
    ScanPreflightError,
    ScanSession,
    _O3D_AVAILABLE,
)
from api.services import scan_service

logger = logging.getLogger(__name__)

# Drivers
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

_WEB_DIR = _API_DIR.parent / "web"
_VERSION_FILE = _REPO_ROOT / "VERSION"
_VERSION = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else "unknown"

# Calibration poses for each camera.
# Pi Camera: X/Y only (Z must not be changed automatically).
# Logitech USB: X/Y/Z (Z used for height).
CAMERA_CALIBRATION_POSES: dict[str, dict[str, float | None]] = {
    "pi": {"x": 0.0, "y": 0.0, "z": None},
    "usb": {"x": 0.0, "y": 0.0, "z": 50.0},
}

# In-memory scan pose memory.  Populated when a calibration pose is reached.
_scan_pose: dict[str, Any] | None = None


@api_bp.after_request
def _add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@api_bp.before_request
def _guard_scan_hardware_reservation():
    """Prevent manual controls from racing a physical acquisition."""
    allowed = {"/api/motor/stop", "/api/motor/status"}
    guarded = (
        request.path.startswith((
            "/api/move/",
            "/api/home/",
            "/api/rotate",
            "/api/laser/",
            "/api/camera/",
            "/api/lidar/",
        ))
        or (
            request.method == "POST"
            and request.path.startswith("/api/scan/pose/")
        )
        or (
            request.method == "POST"
            and request.path == "/api/scan/preflight"
        )
    )
    if request.path in allowed or not guarded:
        return None

    session = globals().get("scan_session")
    reservation = globals().get("_scan_hardware_lock")
    if (
        session is not None
        and bool(getattr(session, "hardware_reserved", False))
    ) or reservation is None or not reservation.acquire(blocking=False):
        return _json_error(
            "Scanner hardware is reserved by an active acquisition",
            409,
            hint="Stop the scan before using manual motor, laser, camera, or LiDAR controls.",
        )
    g.scan_hardware_lock_acquired = True
    return None


@api_bp.after_request
def _release_request_hardware_reservation(response):
    if getattr(g, "scan_hardware_lock_acquired", False):
        g.scan_hardware_lock_acquired = False
        camera_lock = getattr(g, "scan_hardware_operation_lock", None)
        if camera_lock is not None and camera_lock.locked():
            threading.Thread(
                target=_release_after_camera_operation,
                args=(camera_lock,),
                name="camera-hardware-quarantine",
                daemon=True,
            ).start()
        else:
            _scan_hardware_lock.release()
    return response


def _release_after_camera_operation(camera_lock: threading.Lock) -> None:
    camera_lock.acquire()
    camera_lock.release()
    _scan_hardware_lock.release()


@api_bp.route("/", methods=["GET"])
def index():
    return send_from_directory(str(_WEB_DIR), "index.html")


@api_bp.route("/app.js", methods=["GET"])
def web_app_script():
    return send_from_directory(str(_WEB_DIR), "app.js")


@api_bp.route("/style.css", methods=["GET"])
def web_styles():
    return send_from_directory(str(_WEB_DIR), "style.css")


@api_bp.route("/viewer3d.js", methods=["GET"])
def web_3d_viewer_script():
    return send_from_directory(str(_WEB_DIR), "viewer3d.js")


def _initialize_driver(driver: Any, name: str) -> None:
    """Attempt to connect a driver without aborting startup."""
    if driver is None:
        logger.warning("%s not available", name)
        return

    try:
        if not driver.connect():
            last_error = getattr(driver, "last_error", None)
            if last_error is not None:
                logger.warning("%s connection failed", name, exc_info=last_error)
            else:
                logger.warning("%s connection failed", name)
    except Exception as exc:  # pragma: no cover - hardware dependent
        logger.warning("%s connection error", name, exc_info=exc)


def _load_gpiozero_factories() -> tuple[Callable | None, Callable | None]:
    try:
        from gpiozero import OutputDevice, PWMOutputDevice
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("gpiozero import failed: %s", exc)
        return None, None

    def output_device_factory(pin, active_high=True, initial_value=False):
        return OutputDevice(
            pin,
            active_high=active_high,
            initial_value=bool(initial_value),
        )

    def pwm_device_factory(
        pin,
        active_high=True,
        initial_value=False,
        frequency=100,
    ):
        return PWMOutputDevice(
            pin,
            active_high=active_high,
            initial_value=float(initial_value),
            frequency=frequency,
        )

    return output_device_factory, pwm_device_factory


def _create_gpio_driver(enabled: bool, config: dict) -> Any:
    if GPIODriver is None:
        return None
    output_factory = None
    pwm_factory = None
    if enabled:
        output_factory, pwm_factory = _load_gpiozero_factories()
    return GPIODriver(
        simulation=not enabled,
        hardware_config=config,
        output_device_factory=output_factory,
        pwm_device_factory=pwm_factory,
    )


hardware_config = config_manager.load_hardware_config()
application_config = config_manager.load()
pi_gpio_enabled = bool(hardware_config.get("hardware", {}).get("pi_gpio", False))
stm32_enabled = bool(hardware_config.get("hardware", {}).get("mcu"))
serial_config = hardware_config.get("serial", {})
camera_config = hardware_config.get("cameras", {})
scanner_config = application_config.get("scanner", {})


def _simulation_enabled(config: dict[str, Any]) -> bool:
    """Resolve the configured acquisition mode without an implicit fallback."""
    configured_mode = config.get("mode")
    if configured_mode is None:
        return bool(config.get("simulation", False))
    mode = str(configured_mode).strip().lower()
    if mode not in {"real", "simulation"}:
        raise ValueError("scanner.mode must be either 'real' or 'simulation'")
    legacy_mode = "simulation" if bool(config.get("simulation", False)) else "real"
    if "simulation" in config and legacy_mode != mode:
        raise ValueError("scanner.mode and scanner.simulation configure conflicting modes")
    return mode == "simulation"


stm32_driver = (
    STM32Driver(simulation=not stm32_enabled, hardware_config=hardware_config)
    if STM32Driver
    else None
)
gpio_driver = (
    _create_gpio_driver(pi_gpio_enabled, hardware_config)
)
lidar_driver = LidarDriver(
    port=serial_config.get("lidar_port", "/dev/ttyUSB0"),
    baud=int(serial_config.get("lidar_baud", 115200)),
)
pi_camera = PiCamera()
usb_camera = LogitechCamera(device_id=camera_config.get("usb_device_id", "auto"))
_scan_hardware_lock = HardwareReservationLock()
scan_session = ScanSession(
    simulation=_simulation_enabled(scanner_config),
    motor_driver=stm32_driver,
    gpio_driver=gpio_driver,
    cameras={"pi": pi_camera, "usb": usb_camera},
    lidar_driver=lidar_driver,
    config=scanner_config.get("acquisition", {}),
    calibration=hardware_config.get("scan_calibration", {}),
    saved_poses_provider=get_all_saved_poses,
    laser_line_analyzer=analyze_laser_line,
    hardware_reservation=_scan_hardware_lock,
)


def _install_geometric_calibration(calibration: dict[str, Any]) -> None:
    hardware_config["scan_calibration"] = calibration
    scan_session.update_calibration(calibration)


def _current_geometric_calibration() -> dict[str, Any]:
    return copy.deepcopy(hardware_config.get("scan_calibration", {}))


geometric_calibration = GeometricCalibrationService(
    motor_driver=stm32_driver,
    gpio_driver=gpio_driver,
    cameras={"pi": pi_camera, "usb": usb_camera},
    lidar_driver=lidar_driver,
    hardware_reservation=_scan_hardware_lock,
    store=AtomicCalibrationStore(config_manager.CALIBRATION_STATE_PATH),
    config=scanner_config.get("geometric_calibration", {}),
    on_saved=_install_geometric_calibration,
    get_current_calibration=_current_geometric_calibration,
)
reconstruction_engine = ReconstructionEngine(scan_session)
pose_memory = PoseMemory()
_CALIBRATION_LIDAR_TARGET_MM = {"pi": 300.0, "usb": 300.0}
_CALIBRATION_LIDAR_TOLERANCE_MM = 20.0
CAMERA_FRAME_TIMEOUT_SECONDS = 8.0
CAMERA_TEST_TIMEOUT_SECONDS = 10.0
_camera_operation_locks = {
    "pi": threading.Lock(),
    "usb": threading.Lock(),
}
_laser_operation_lock = threading.Lock()

_initialize_driver(stm32_driver, "STM32Driver")
_initialize_driver(gpio_driver, "GPIODriver")


def _board_temperature_control_loop() -> None:
    while True:
        if stm32_driver is not None:
            try:
                stm32_driver.update_board_fan_auto_control()
            except Exception:
                logger.exception("Creality temperature control failed")
        time.sleep(float(serial_config.get("temperature_poll_interval_s", 5)))


threading.Thread(target=_board_temperature_control_loop, name="board-temperature-control", daemon=True).start()


def _get_camera(camera_name: str):
    cameras = {
        "pi": pi_camera,
        "usb": usb_camera,
    }
    return cameras.get(camera_name)


def _ensure_camera_open(camera) -> bool:
    return camera.is_open or camera.open()


class CameraOperationBusy(RuntimeError):
    """Raised when another request already owns a camera."""


class CameraOperationTimeout(TimeoutError):
    """Raised when a camera operation exceeds its endpoint deadline."""


class CameraLaserControlError(RuntimeError):
    """Raised when lasers cannot be safely managed for camera diagnostics."""


def _run_camera_operation(
    camera_name: str,
    operation: Callable[[], Any],
    timeout_seconds: float,
) -> Any:
    """Run one operation per camera and bound the request wait time.

    The worker owns the lock until it actually exits. If libcamera or OpenCV
    remains stuck after the request deadline, later requests fail fast instead
    of starting more work against the same camera.
    """
    lock = _camera_operation_locks[camera_name]
    if not lock.acquire(blocking=False):
        raise CameraOperationBusy(f"Camera {camera_name} busy")
    if has_request_context() and getattr(g, "scan_hardware_lock_acquired", False):
        g.scan_hardware_operation_lock = lock

    completed = threading.Event()
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["value"] = operation()
        except Exception as exc:
            outcome["error"] = exc
        finally:
            lock.release()
            completed.set()

    try:
        worker = threading.Thread(
            target=run,
            name=f"camera-{camera_name}-operation",
            daemon=True,
        )
        worker.start()
    except Exception:
        lock.release()
        raise

    if not completed.wait(timeout_seconds):
        raise CameraOperationTimeout(
            f"Camera {camera_name} operation exceeded {timeout_seconds:.1f}s"
        )
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def _camera_operation_error(camera_name: str, exc: Exception):
    if isinstance(exc, CameraOperationBusy):
        return _json_error(
            f"Camera {camera_name} busy; another capture or analysis is running",
            409,
        )
    if isinstance(exc, CameraOperationTimeout):
        logger.error("%s", exc)
        return _json_error(
            f"Camera {camera_name} operation timed out; retry after it finishes",
            504,
        )
    if isinstance(exc, CameraLaserControlError):
        logger.error("%s", exc)
        return _json_error(str(exc), 503)
    logger.exception("Camera %s operation failed", camera_name)
    return _json_error("Internal server error", 500)


def _ensure_lidar_connected() -> bool:
    return lidar_driver.connected or lidar_driver.connect()


def _gpio_driver_ready() -> bool:
    if gpio_driver is None:
        return False
    simulation = getattr(gpio_driver, "simulation", None)
    hardware_available = getattr(gpio_driver, "hardware_available", None)
    if simulation is not None and hardware_available is not None:
        return bool(simulation or hardware_available)
    status_fn = getattr(gpio_driver, "status", None)
    if callable(status_fn):
        try:
            status = status_fn()
            return bool(status.get("simulation") or status.get("hardware_available"))
        except Exception:
            return False
    return False


def _stm32_driver_ready() -> bool:
    if stm32_driver is None:
        return False
    return bool(getattr(stm32_driver, "connected", False))


def _board_temperature_status(driver: Any) -> dict[str, Any]:
    """Return the extended status while retaining compatibility with test drivers."""
    status_fn = getattr(driver, "get_temperature_status", None)
    if callable(status_fn):
        return status_fn()
    temperature = driver.read_board_temperature()
    return {
        "sensor": "PC5",
        "sensor_type": "EPCOS 100K B57560G104F",
        "temperature_c": temperature,
        "board_c": temperature,
        "connected": temperature is not None,
        "error": None if temperature is not None else "Temperature probe PC5 unavailable",
        "fan": "PA8",
        "fan_auto": False,
        "fan_on": False,
    }


def _json_error(
    message: str,
    status_code: int = 400,
    *,
    detail: str | None = None,
    hint: str | None = None,
):
    payload = {"success": False, "error": message}
    if detail is not None:
        payload["detail"] = detail
    if hint is not None:
        payload["hint"] = hint
    return jsonify(payload), status_code


def _gpio_ready() -> bool:
    return bool(
        gpio_driver is not None
        and (
            getattr(gpio_driver, "simulation", False)
            or getattr(gpio_driver, "hardware_available", False)
        )
    )


def _stm32_ready() -> bool:
    return bool(stm32_driver is not None and getattr(stm32_driver, "connected", False))


def _serialized_motor_route(*, allow_while_scanning: bool = False):
    def decorate(route):
        @wraps(route)
        def wrapped(*args, **kwargs):
            if not scan_service.acquire_motor_operation():
                return _json_error("Motor control busy", 409)
            try:
                if scan_session.has_outstanding_operations():
                    return _json_error(
                        "A timed-out hardware operation is still completing",
                        409,
                    )
                if (
                    not allow_while_scanning
                    and scan_session.status().get("scanning", False)
                ):
                    return _json_error("Motor movement unavailable during scan", 409)
                return route(*args, **kwargs)
            finally:
                scan_service.release_motor_operation()

        return wrapped

    return decorate


def _runtime_capabilities() -> dict[str, Any]:
    camera_status = {
        "pi": bool(pi_camera and pi_camera.is_open),
        "usb": bool(usb_camera and usb_camera.is_open),
    }
    _configure_scan_session_hardware()
    acquisition = scan_session.readiness(probe=False)
    simulation_mode = acquisition["mode"] == "simulation"
    return {
        "camera_available": camera_status,
        "gpio_available": _gpio_ready(),
        "open3d_available": bool(_O3D_AVAILABLE),
        "acquisition_backend_ready": acquisition["ready"],
        "acquisition_blockers": acquisition["blockers"],
        "acquisition_mode": acquisition["mode"],
        "simulation_mode": simulation_mode,
    }


def _configure_scan_session_hardware() -> None:
    """Keep the acquisition session attached to the shared runtime drivers."""
    scan_session.configure_hardware(
        motor_driver=stm32_driver,
        gpio_driver=gpio_driver,
        cameras={"pi": pi_camera, "usb": usb_camera},
        lidar_driver=lidar_driver,
    )


def _lidar_validation(camera_name: str, lidar_distance_mm: float | None) -> dict[str, Any]:
    expected = _CALIBRATION_LIDAR_TARGET_MM.get(camera_name, 300.0)
    validation: dict[str, Any] = {
        "lidar_connected": lidar_distance_mm is not None,
        "lidar_expected_mm": expected,
        "lidar_tolerance_mm": _CALIBRATION_LIDAR_TOLERANCE_MM,
        "lidar_out_of_tolerance": False,
    }
    if lidar_distance_mm is None:
        return validation
    validation["lidar_out_of_tolerance"] = (
        abs(float(lidar_distance_mm) - expected) > _CALIBRATION_LIDAR_TOLERANCE_MM
    )
    return validation


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


# Files written/read by the standalone systemd fan-auto-pwm service (see docs).
_PI4_FAN_STATE_FILE = Path("/run/fan_state.json")
_PI4_FAN_CONFIG_FILE = Path("/etc/horaltscanner/fan_config.json")
_PI4_FAN_THERMAL_FILE = Path("/sys/class/thermal/thermal_zone0/temp")


def _read_pi4_cpu_temperature() -> float | None:
    try:
        raw = _PI4_FAN_THERMAL_FILE.read_text().strip()
        return float(raw) / 1000.0
    except (OSError, ValueError):
        return None


def _read_pi4_fan_auto_status() -> dict[str, Any]:
    """Build the read-only status payload for the automatic Pi4 fan.

    The fan itself is fully managed by an independent system service
    (fan-auto-pwm.service) driving hardware PWM based on CPU temperature.
    This endpoint only reports telemetry; it exposes no control knobs.
    """
    temp_c = _read_pi4_cpu_temperature()
    fan_percent: int | None = None
    t_min = 30
    t_max = 50

    if _PI4_FAN_CONFIG_FILE.exists():
        try:
            cfg = json.loads(_PI4_FAN_CONFIG_FILE.read_text())
            if isinstance(cfg, dict):
                t_min = cfg.get("t_min", t_min)
                t_max = cfg.get("t_max", t_max)
        except (OSError, ValueError):
            pass

    if _PI4_FAN_STATE_FILE.exists():
        try:
            state = json.loads(_PI4_FAN_STATE_FILE.read_text())
            if isinstance(state, dict):
                if "fan_percent" in state:
                    fan_percent = int(state.get("fan_percent"))
                if state.get("temp_c") is not None:
                    temp_c = state.get("temp_c")
        except (OSError, ValueError, TypeError):
            pass

    return {
        "mode": "auto",
        "temp_c": temp_c,
        "fan_percent": fan_percent,
        "t_min": t_min,
        "t_max": t_max,
    }


@api_bp.route("/api/fan/pi4/status", methods=["GET"])
def fan_pi4_status():
    """Read-only telemetry for the automatic Pi4 fan (no manual control)."""
    try:
        return jsonify(_read_pi4_fan_auto_status())
    except Exception:
        logger.exception("Pi4 fan status route failed")
        return _json_error("Internal server error", 500)


@api_bp.route("/api/laser/<side>", methods=["POST"])
def laser(side: str):
    data = request.get_json(silent=True) or {}
    state = bool(data.get("state", False))

    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)

    if not _laser_operation_lock.acquire(blocking=False):
        return _json_error("Laser control busy; camera diagnostic in progress", 409)
    try:
        try:
            success = gpio_driver.laser_on(side) if state else gpio_driver.laser_off(side)
            if not success:
                return _json_error("Failed to update laser state")

            return jsonify({"success": True, "status": gpio_driver.get_laser_status()})
        except Exception:
            logger.exception("Laser route failed")
            return _json_error("Internal server error", 500)
    finally:
        _laser_operation_lock.release()


@api_bp.route("/api/led/color", methods=["POST"])
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


@api_bp.route("/api/move/<axis>", methods=["POST"])
@_serialized_motor_route()
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


@api_bp.route("/api/home/<target>", methods=["POST"])
@_serialized_motor_route()
def home(target: str):
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        success = stm32_driver.home_motor(target)
        if not success:
            return _json_error("Failed to home motor")
        scan_session.clear_motion_fault(target)

        return jsonify({"success": True, "status": stm32_driver.get_motor_status()})
    except Exception:
        logger.exception("Home route failed")
        return _json_error("Internal server error", 500)


@api_bp.route("/api/motor/status", methods=["GET", "POST"])
def motor_status():
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        return jsonify({"success": True, "status": stm32_driver.get_motor_status()})
    except Exception:
        logger.exception("Motor status route failed")
        return _json_error("Internal server error", 500)


@api_bp.route("/api/motor/stop", methods=["POST"])
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


@api_bp.route("/api/fan/pi", methods=["POST"])
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


@api_bp.route("/api/fan/creality", methods=["POST"])
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


@api_bp.route("/api/fan/temperature", methods=["POST"])
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


@api_bp.route("/api/fan/status", methods=["GET"])
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


@api_bp.route("/api/temperature/board", methods=["GET"])
@api_bp.route("/api/temperature/creality", methods=["GET"])
def temperature_board():
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        status = _board_temperature_status(stm32_driver)
        if not status["connected"]:
            return jsonify({"success": False, "status": status}), 502
        return jsonify({"success": True, "status": status})
    except Exception:
        logger.exception("Board temperature route failed")
        return _json_error("Internal server error", 500)


@api_bp.route("/api/temperature/all", methods=["GET"])
def temperature_all():
    if stm32_driver is None and gpio_driver is None:
        return _json_error("Temperature drivers unavailable", 503)

    try:
        status: dict[str, Any] = {
            "sensor_pin": "PC5",
            "sensor_type": "EPCOS 100K B57560G104F",
        }
        if stm32_driver is not None:
            board = _board_temperature_status(stm32_driver)
            status.update(board)
            status["board_c"] = board["temperature_c"]
        if gpio_driver is not None:
            status["pi_cpu_c"] = gpio_driver.read_cpu_temperature()
        return jsonify({"success": True, "status": status})
    except Exception:
        logger.exception("All temperature route failed")
        return _json_error("Internal server error", 500)


@api_bp.route("/api/laser/status", methods=["GET"])
def laser_status():
    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)
    try:
        return jsonify({"success": True, "status": gpio_driver.get_laser_status()})
    except Exception:
        logger.exception("Laser status route failed")
        return _json_error("Internal server error", 500)


@api_bp.route("/api/led/status", methods=["GET"])
def led_status():
    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)
    try:
        return jsonify({"success": True, "status": gpio_driver.get_led_status()})
    except Exception:
        logger.exception("LED status route failed")
        return _json_error("Internal server error", 500)


@api_bp.route("/api/lidar/read", methods=["POST"])
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


@api_bp.route("/api/lidar/calibrate", methods=["POST"])
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


@api_bp.route("/api/camera/<camera_name>/frame", methods=["GET"])
def camera_frame(camera_name: str):
    camera = _get_camera(camera_name)
    if camera is None:
        return _json_error("Unknown camera", 404)

    def capture():
        if not _ensure_camera_open(camera):
            return False, None
        return True, camera.capture_jpeg()

    try:
        available, jpeg = _run_camera_operation(
            camera_name,
            capture,
            CAMERA_FRAME_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return _camera_operation_error(camera_name, exc)
    if not available:
        return _json_error("Camera unavailable", 503)
    if jpeg is None:
        return _json_error("Camera capture failed", 502)
    return Response(jpeg, mimetype="image/jpeg")


@api_bp.route("/api/camera/<camera_name>/status", methods=["GET"])
def camera_status(camera_name: str):
    camera = _get_camera(camera_name)
    if camera is None:
        return _json_error("Unknown camera", 404)
    try:
        available = _run_camera_operation(
            camera_name,
            lambda: _ensure_camera_open(camera),
            CAMERA_FRAME_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return _camera_operation_error(camera_name, exc)
    return jsonify({
        "success": True,
        "camera": camera_name,
        "available": available,
        "error": None if available else getattr(camera, "last_error", None),
    })


@api_bp.route("/api/camera/<camera_name>/test", methods=["POST"])
def camera_test(camera_name: str):
    camera = _get_camera(camera_name)
    if camera is None:
        return _json_error("Unknown camera", 404)

    def capture_and_analyze():
        def capture():
            available = _ensure_camera_open(camera)
            return available, camera.capture_jpeg() if available else None

        if camera_name == "pi" and gpio_driver is not None:
            with _laser_operation_lock:
                previous_laser_status = gpio_driver.get_laser_status()
                restore_failures = []
                try:
                    for laser_side in ("left", "right"):
                        if not gpio_driver.laser_off(laser_side):
                            raise CameraLaserControlError(
                                "Unable to disable lasers for Pi Camera test"
                            )
                    available, jpeg = capture()
                finally:
                    for laser_side in ("left", "right"):
                        restore = (
                            gpio_driver.laser_on
                            if previous_laser_status.get(laser_side, False)
                            else gpio_driver.laser_off
                        )
                        try:
                            if not restore(laser_side):
                                restore_failures.append(laser_side)
                        except Exception as exc:
                            logger.error(
                                "Could not restore %s laser after camera test: %s",
                                laser_side,
                                exc,
                            )
                            restore_failures.append(laser_side)
                    if restore_failures:
                        raise CameraLaserControlError(
                            "Unable to restore laser state after Pi Camera test"
                        )
        else:
            available, jpeg = capture()

        if not available or jpeg is None:
            return available, jpeg, None
        return True, jpeg, analyze_camera_frame(jpeg)

    try:
        available, jpeg, result = _run_camera_operation(
            camera_name,
            capture_and_analyze,
            CAMERA_TEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return _camera_operation_error(camera_name, exc)
    if not available:
        return _json_error("Camera unavailable", 503)
    if jpeg is None:
        return _json_error("Camera capture failed", 502)
    if not result.get("analysis_available", False):
        return _json_error("OpenCV camera analysis unavailable", 503)
    return jsonify({"success": True, "camera": camera_name, "result": result})


# ---------------------------------------------------------------------------
# Camera calibration pose endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/api/camera/<camera_name>/goto_calibration_pose", methods=["POST"])
@_serialized_motor_route()
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
        return _json_error("Déplacement moteur échoué", 503)

    lidar_dist = read_lidar_distance(lidar_driver)
    lidar_validation = _lidar_validation(camera_name, lidar_dist)

    camera_label = "Pi Camera" if camera_name == "pi" else "Caméra USB Logitech"
    instruction = f"Pose de calibration {camera_label} atteinte."
    if lidar_dist is not None:
        instruction += f" Distance TF-Luna : {lidar_dist:.1f} mm."
        if lidar_validation["lidar_out_of_tolerance"]:
            instruction += " ⚠️ Hors tolérance."

    return jsonify({
        "success": True,
        "camera": camera_name,
        "pose": pose,
        "moved_axes": moved,
        "lidar_distance_mm": lidar_dist,
        **lidar_validation,
        "instruction": instruction,
    })


@api_bp.route("/api/camera/<camera_name>/save_scan_pose", methods=["POST"])
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


@api_bp.route("/api/camera/<camera_name>/goto_scan_pose", methods=["POST"])
@_serialized_motor_route()
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
        return _json_error("Déplacement moteur échoué", 503)

    lidar_dist = read_lidar_distance(lidar_driver)
    lidar_validation = _lidar_validation(camera_name, lidar_dist)

    camera_label = "Pi Camera" if camera_name == "pi" else "Caméra USB Logitech"
    instruction = f"Retour à la pose de scan {camera_label}."
    if lidar_dist is not None:
        instruction += f" Distance TF-Luna : {lidar_dist:.1f} mm."
        if lidar_validation["lidar_out_of_tolerance"]:
            instruction += " ⚠️ Hors tolérance."

    return jsonify({
        "success": True,
        "camera": camera_name,
        "pose": saved,
        "moved_axes": moved,
        "lidar_distance_mm": lidar_dist,
        **lidar_validation,
        "instruction": instruction,
    })


@api_bp.route("/api/camera/scan_poses", methods=["GET"])
def camera_scan_poses():
    """Return all saved scan poses.

    Returns JSON:
      - poses: dict keyed by camera name
    """
    return jsonify({"success": True, "poses": pose_memory.all_poses()})


@api_bp.route("/api/laser/align/<side>", methods=["POST"])
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

    side_label = "gauche" if side == "left" else "droit"

    def capture_and_analyze_laser():
        if not _ensure_camera_open(pi_camera):
            return False, None, None
        with _laser_operation_lock:
            if not gpio_driver.laser_off("left"):
                raise CameraLaserControlError("Unable to disable left laser")
            if not gpio_driver.laser_off("right"):
                raise CameraLaserControlError("Unable to disable right laser")
            if not gpio_driver.laser_on(side):
                raise CameraLaserControlError(f"Unable to enable {side} laser")
            try:
                jpeg = pi_camera.capture_jpeg()
            finally:
                if not gpio_driver.laser_off(side):
                    logger.error("Unable to disable %s laser after alignment", side)
        return (
            True,
            jpeg,
            analyze_laser_line(jpeg) if jpeg is not None else None,
        )

    try:
        available, jpeg, result = _run_camera_operation(
            "pi",
            capture_and_analyze_laser,
            CAMERA_TEST_TIMEOUT_SECONDS,
        )
    except CameraOperationTimeout as exc:
        try:
            gpio_driver.laser_off(side)
        except Exception:
            logger.exception("Emergency laser shutdown failed after alignment timeout")
        return _camera_operation_error("pi", exc)
    except Exception as exc:
        return _camera_operation_error("pi", exc)

    if not available:
        return _json_error("Pi Camera unavailable", 503)
    if jpeg is None:
        return _json_error("Pi Camera capture failed", 503)

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


@api_bp.route("/api/camera/calibrate/pose/<camera_name>", methods=["POST"])
@_serialized_motor_route()
def camera_calibrate_pose(camera_name: str):
    """Move motors to the calibration pose for the requested camera.

    - Pi Camera (``pi``): moves X and Y only; Z is left unchanged.
    - Logitech USB (``usb``): moves X, Y, and Z.

    Optionally reads TF-Luna distance for precision validation.

    Returns JSON with ``ok``, ``camera``, ``pose``, ``axes_moved``,
    ``lidar_distance_mm``, and ``lidar_within_tolerance``.
    """
    if camera_name not in ("pi", "usb"):
        return _json_error("Caméra invalide ; utilisez 'pi' ou 'usb'", 400)

    if stm32_driver is None:
        return _json_error("Pilote STM32 non disponible", 503)

    lidar: Any = lidar_driver if (lidar_driver is not None and lidar_driver.connected) else None

    result = move_to_calibration_pose(camera_name, stm32_driver, lidar_driver=lidar)
    if not result.get("ok"):
        return _json_error(result.get("error", "Erreur inconnue"), 500)

    return jsonify({"success": True, **result})


@api_bp.route("/api/scan/pose", methods=["GET"])
def scan_pose_get():
    """Return all saved scan poses."""
    return jsonify({"success": True, "poses": get_all_saved_poses()})


def _geometric_calibration_options(data):
    if not isinstance(data, dict):
        raise ValueError("calibration request must be a JSON object")
    start = data.get("starting_pose_mm", data.get("start_pose"))
    lidar = data.get("lidar", data.get("lidar_measurements"))
    result = {}

    def finite_vector(value, label, keys=None):
        if keys is not None and isinstance(value, dict):
            value = [value.get(key) for key in keys]
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f"{label} must contain exactly three values")
        numbers = [float(item) for item in value]
        if not all(math.isfinite(item) for item in numbers):
            raise ValueError(f"{label} values must be finite")
        return numbers

    if start is not None:
        values = finite_vector(start, "starting pose", ("x", "y", "z"))
        result["starting_pose_mm"] = dict(zip(("x", "y", "z"), values))
    if lidar is not None:
        if not isinstance(lidar, dict):
            raise ValueError("lidar measurements must be an object")
        result["lidar"] = {
            "origin_mm": finite_vector(lidar.get("origin_mm"), "TF-Luna origin_mm"),
            "direction": finite_vector(lidar.get("direction"), "TF-Luna direction"),
            "reference_z_mm": float(
                lidar.get(
                    "reference_z_mm",
                    result.get("starting_pose_mm", {}).get("z", 20.0),
                )
            ),
        }
        if not math.isfinite(result["lidar"]["reference_z_mm"]):
            raise ValueError("TF-Luna reference_z_mm must be finite")
    return result


@api_bp.route("/api/calibration/geometric/preflight", methods=["POST"])
def geometric_calibration_preflight():
    try:
        options = _geometric_calibration_options(request.get_json(silent=True) or {})
    except (TypeError, ValueError) as exc:
        return _json_error(str(exc), 400)
    result = geometric_calibration.preflight(options)
    return jsonify({"success": True, **result})


@api_bp.route("/api/calibration/geometric/start", methods=["POST"])
def geometric_calibration_start():
    try:
        options = _geometric_calibration_options(request.get_json(silent=True) or {})
    except (TypeError, ValueError) as exc:
        return _json_error(str(exc), 400)
    readiness = geometric_calibration.preflight(options)
    if not readiness["ready"]:
        return jsonify({
            "success": False,
            "error": "Geometric calibration preflight failed",
            "blockers": readiness["blockers"],
        }), 409
    try:
        status = geometric_calibration.start(options)
    except CalibrationError as exc:
        return _json_error(str(exc), 409)
    return jsonify({"success": True, **status}), 202


@api_bp.route("/api/calibration/geometric/status", methods=["GET"])
def geometric_calibration_status():
    return jsonify({"success": True, **geometric_calibration.status()})


@api_bp.route("/api/calibration/geometric/cancel", methods=["POST"])
def geometric_calibration_cancel():
    return jsonify({"success": True, **geometric_calibration.cancel()})


@api_bp.route("/api/calibration/geometric/rollback", methods=["POST"])
def geometric_calibration_rollback():
    try:
        result = geometric_calibration.rollback()
    except CalibrationError as exc:
        return _json_error(str(exc), 409)
    return jsonify({"success": True, **result})


@api_bp.route("/api/calibration/geometric/report", methods=["GET"])
def geometric_calibration_report():
    try:
        report = geometric_calibration.report()
    except CalibrationError as exc:
        return _json_error(str(exc), 404)
    if request.args.get("download") == "1":
        return send_file(
            BytesIO(json.dumps(report, indent=2).encode("utf-8")),
            mimetype="application/json",
            as_attachment=True,
            download_name="horalscanner-calibration-report.json",
        )
    return jsonify({"success": True, **report})


@api_bp.route("/api/scan/pose/save", methods=["POST"])
def scan_pose_save():
    """Save the current motor position as the scan reference pose for a camera.

    Body JSON: ``{"camera": "pi"|"usb"}``
    """
    data = request.get_json(silent=True) or {}
    camera_name = str(data.get("camera", "")).strip()
    if camera_name not in ("pi", "usb"):
        return _json_error("Caméra invalide ; utilisez 'pi' ou 'usb'", 400)

    if stm32_driver is None:
        return _json_error("Pilote STM32 non disponible", 503)

    result = save_current_pose(camera_name, stm32_driver)
    if not result.get("ok"):
        return _json_error(result.get("error", "Erreur inconnue"), 500)

    return jsonify({"success": True, **result})


@api_bp.route("/api/scan/pose/restore", methods=["POST"])
@_serialized_motor_route()
def scan_pose_restore():
    """Move motors back to the saved scan pose for a camera.

    Body JSON: ``{"camera": "pi"|"usb"}``
    """
    data = request.get_json(silent=True) or {}
    camera_name = str(data.get("camera", "")).strip()
    if camera_name not in ("pi", "usb"):
        return _json_error("Caméra invalide ; utilisez 'pi' ou 'usb'", 400)

    if stm32_driver is None:
        return _json_error("Pilote STM32 non disponible", 503)

    result = restore_scan_pose(camera_name, stm32_driver)
    if not result.get("ok"):
        return _json_error(result.get("error", "Aucune pose mémorisée"), 404)

    return jsonify({"success": True, **result})


@api_bp.route("/api/scan/start", methods=["POST"])
@_serialized_motor_route(allow_while_scanning=True)
def scan_start():
    _configure_scan_session_hardware()
    try:
        scan_session.start()
    except ScanPreflightError as exc:
        return jsonify({
            "success": False,
            "error": "Real scan preflight failed",
            "detail": "; ".join(exc.blockers),
            "hint": "Resolve every preflight blocker; physical scans never fall back to simulation.",
            "blockers": exc.blockers,
            "status": scan_session.status(),
        }), 409
    except RuntimeError as exc:
        return _json_error(
            str(exc),
            409,
            detail="The requested scan could not be started.",
            hint="Check /api/scan/preflight and resolve its blockers.",
        )
    status = scan_session.status()
    return jsonify({
        "success": True,
        "mode": status["mode"],
        "motor_preparation": status.get("motor_preparation"),
        "status": status,
        "hint": (
            "Explicit synthetic scan started."
            if status["simulation"]
            else "Physical acquisition started with calibrated hardware."
        ),
    })


@api_bp.route("/api/scan/preflight", methods=["GET", "POST"])
def scan_preflight():
    """Report blockers; POST deliberately probes cameras, LiDAR, and laser-off control."""
    _configure_scan_session_hardware()
    if request.method == "POST":
        reserved_probe = getattr(
            scan_session,
            "probe_readiness_with_reservation",
            None,
        )
        if callable(reserved_probe):
            g.scan_hardware_lock_acquired = False
            result = reserved_probe()
        else:
            result = scan_session.readiness(probe=True)
    else:
        result = scan_session.readiness(probe=False)
    return jsonify({"success": True, **result}), 200


@api_bp.route("/api/scan/stop", methods=["POST"])
def scan_stop():
    scan_session.stop()
    return jsonify({"success": True, "status": scan_session.status()})


@api_bp.route("/api/scan/status", methods=["GET"])
def scan_status():
    _configure_scan_session_hardware()
    return jsonify({"success": True, "status": scan_session.status()})


@api_bp.route("/api/scan/pointcloud", methods=["GET"])
def scan_pointcloud():
    return jsonify({"success": True, **scan_session.get_pointcloud()})


@api_bp.route("/api/model/reconstruct", methods=["POST"])
def model_reconstruct():
    result = reconstruction_engine.reconstruct()
    if not result["ok"]:
        detail = "The current scan does not contain enough points for mesh reconstruction."
        if result.get("stl_size", 0) > 0:
            detail = f"Only {result.get('stl_size', 0)} bytes of model data were produced."
        return _json_error(
            result.get("error", "Reconstruction failed"),
            409,
            detail=detail,
            hint="Start a scan and collect enough points before reconstructing a model.",
        )
    # When reconstruction is running in the background, the caller should
    # poll /api/model/status for progress/result rather than expecting the
    # final mesh inline.
    return jsonify({"success": True, **result})


@api_bp.route("/api/model/status", methods=["GET"])
def model_status():
    return jsonify({"success": True, **reconstruction_engine.status()})


@api_bp.route("/api/model/cancel", methods=["POST"])
def model_cancel():
    reconstruction_engine.cancel()
    return jsonify({"success": True, **reconstruction_engine.status()})


@api_bp.route("/api/model/current", methods=["GET"])
def model_current():
    model_format = request.args.get("format", "stl").lower()
    if model_format not in {"stl", "amf"}:
        return _json_error("Format must be stl or amf", 400)
    model = reconstruction_engine.get_model(model_format)
    if model is None:
        return _json_error(
            "No reconstructed model available",
            404,
            detail=f"No {model_format.upper()} model exists for the current session.",
            hint="Run a scan and reconstruct the model before exporting it.",
        )
    return send_file(
        BytesIO(model),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=f"horalscanner-model.{model_format}",
    )


@api_bp.route("/api/camera/<camera_name>/calibration-pose", methods=["POST"])
@_serialized_motor_route()
def camera_calibration_pose(camera_name: str):
    """Move motors to the calibration pose for the selected camera.

    - Pi Camera  : moves X and Y only; Z is left unchanged.
    - Logitech USB: moves X, Y, and Z.

    After reaching the pose the current position is memorized as the scan
    reference pose.  If TF-Luna is available the measured distance is
    included in the response.
    """
    global _scan_pose

    pose = CAMERA_CALIBRATION_POSES.get(camera_name)
    if pose is None:
        return _json_error("Camera inconnue; utilisez 'pi' ou 'usb'", 404)

    if stm32_driver is None:
        return _json_error("Pilote STM32 indisponible", 503)

    try:
        target_pose = {
            axis: float(target)
            for axis in ("x", "y", "z")
            if (target := pose.get(axis)) is not None
        }
        axes_moved = move_to_pose(stm32_driver, target_pose)

        motor_status = stm32_driver.get_motor_status()
        positions = motor_status.get("positions", {})

        # Memorize the pose for scan start
        _scan_pose = {
            "camera": camera_name,
            "x": positions.get("x"),
            "y": positions.get("y"),
            "z": positions.get("z"),
        }

        # Optional TF-Luna distance reading
        distance_mm = None
        if _ensure_lidar_connected():
            distance_mm = lidar_driver.read_distance_mm()
            if distance_mm is not None:
                distance_mm = round(distance_mm, 1)

        camera_label = "Pi Camera V3" if camera_name == "pi" else "Logitech C270"
        axes_label = "/".join(a.upper() for a in axes_moved)
        return jsonify({
            "success": True,
            "camera": camera_name,
            "camera_label": camera_label,
            "axes_moved": axes_moved,
            "message": f"Pose de calibration {camera_label} ({axes_label}) atteinte et memorisee.",
            "motor_status": motor_status,
            "scan_pose": _scan_pose,
            "lidar_distance_mm": distance_mm,
        })
    except Exception:
        logger.exception("Calibration pose route failed")
        return _json_error("Erreur interne", 500)


@api_bp.route("/api/camera/scan-pose/save", methods=["POST"])
def camera_scan_pose_save():
    """Save the current motor position as the scan pose for the given camera."""
    global _scan_pose

    if stm32_driver is None:
        return _json_error("Pilote STM32 indisponible", 503)

    data = request.get_json(silent=True) or {}
    camera_name = str(data.get("camera", "pi"))
    if camera_name not in CAMERA_CALIBRATION_POSES:
        return _json_error("Camera inconnue; utilisez 'pi' ou 'usb'", 404)

    try:
        motor_status = stm32_driver.get_motor_status()
        positions = motor_status.get("positions", {})
        _scan_pose = {
            "camera": camera_name,
            "x": positions.get("x"),
            "y": positions.get("y"),
            "z": positions.get("z"),
        }
        camera_label = "Pi Camera V3" if camera_name == "pi" else "Logitech C270"
        return jsonify({
            "success": True,
            "message": f"Position actuelle memorisee pour {camera_label}.",
            "scan_pose": _scan_pose,
        })
    except Exception:
        logger.exception("Scan pose save route failed")
        return _json_error("Erreur interne", 500)


@api_bp.route("/api/camera/scan-pose", methods=["GET"])
def camera_scan_pose_get():
    """Return the memorized scan pose."""
    if _scan_pose is None:
        return jsonify({"success": True, "scan_pose": None, "message": "Aucune pose memorisee."})
    return jsonify({"success": True, "scan_pose": _scan_pose})


@api_bp.route("/api/camera/scan-pose/goto", methods=["POST"])
@_serialized_motor_route()
def camera_scan_pose_goto():
    """Move motors back to the memorized scan pose."""
    if _scan_pose is None:
        return _json_error("Aucune pose memorisee. Lancez d'abord une calibration.", 409)

    if stm32_driver is None:
        return _json_error("Pilote STM32 indisponible", 503)

    try:
        target_pose = {
            axis: float(target)
            for axis in ("x", "y", "z")
            if (target := _scan_pose.get(axis)) is not None
        }
        move_to_pose(stm32_driver, target_pose)

        motor_status = stm32_driver.get_motor_status()
        camera_label = "Pi Camera V3" if _scan_pose.get("camera") == "pi" else "Logitech C270"
        return jsonify({
            "success": True,
            "message": f"Retour a la pose {camera_label} effectue.",
            "scan_pose": _scan_pose,
            "motor_status": motor_status,
        })
    except Exception:
        logger.exception("Scan pose goto route failed")
        return _json_error("Erreur interne", 500)


@api_bp.route("/api/status", methods=["GET"])
def api_status():
    gpio_ready = _gpio_ready()
    stm32_ready = _stm32_ready()
    capabilities = _runtime_capabilities()
    gpio_error = None
    if not gpio_ready:
        raw_error = getattr(gpio_driver, "last_error", None)
        gpio_error = str(raw_error) if raw_error is not None else "GPIO driver unavailable"
    stm32_error = None
    if not stm32_ready:
        raw_error = getattr(stm32_driver, "last_error", None)
        stm32_error = str(raw_error) if raw_error is not None else "STM32 driver unavailable"
    status_payload = {
        "api": "ok",
        "gpio_driver": gpio_ready,
        "gpio_error": gpio_error,
        "stm32_driver": stm32_ready,
        "stm32_connected": stm32_ready,
        "stm32_error": stm32_error,
        "version": _VERSION,
        "simulation_mode": capabilities["simulation_mode"],
    }
    return jsonify({
        "success": True,
        "status": status_payload,
        "capabilities": capabilities,
    })


@api_bp.route("/api/capabilities", methods=["GET"])
def api_capabilities():
    return jsonify({"success": True, "capabilities": _runtime_capabilities()})


@api_bp.route("/api/health", methods=["GET"])
@api_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


def _create_standalone_app() -> Flask:
    app = Flask(__name__)
    try:
        from software.api.middleware.errors import register_error_handlers

        register_error_handlers(app)
    except Exception as exc:  # pragma: no cover - startup best effort
        logger.warning("Error middleware unavailable: %s", exc)
    app.register_blueprint(api_bp)
    try:
        from software.api.blueprints.scan import scan_bp

        app.register_blueprint(scan_bp)
    except Exception as exc:  # pragma: no cover - startup best effort
        logger.warning("Scan blueprint unavailable: %s", exc)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(api_bp)
    app.run(host="0.0.0.0", port=5000, debug=False)
