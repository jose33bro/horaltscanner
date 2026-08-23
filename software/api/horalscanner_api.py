"""
HoralScanner PRO - Main REST API
Replaces creality_api.py with a complete implementation.

Run:  python software/api/horalscanner_api.py
      (or via systemd service)
"""

import base64
import logging
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_API_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _API_DIR.parent.parent
_WEB_DIR = _REPO_ROOT / "software" / "web"

sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_API_DIR))

import config_manager
from scanner_engine import ReconstructionEngine, ScanSession
from camera_driver import LogitechCamera, PiCamera
from lidar_driver import LidarDriver
from slicer_bridge import SlicerBridge
from moonraker_client import MoonrakerClient

# New drivers and API blueprints
sys.path.insert(0, str(_REPO_ROOT / "software" / "drivers"))
from stm32_driver import STM32Driver
from gpio_driver import GPIODriver
from motor_control import motor_bp, init_driver as _init_motor_driver
from laser_control import laser_bp, init_driver as _init_laser_driver
from led_control import led_bp, init_driver as _init_led_driver

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder=str(_WEB_DIR), static_url_path="")
CORS(app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state (singletons)
# ---------------------------------------------------------------------------
_cfg = config_manager.load()
_hardware_cfg = config_manager.load_hardware_config()

_scan_session = ScanSession()
_reconstruction = ReconstructionEngine(_scan_session)
_logitech = LogitechCamera(device_id=0)
_picam = PiCamera()
_lidar = LidarDriver(port=_hardware_cfg.get("serial", {}).get("lidar_port", "/dev/ttyUSB0"))
_slicer = SlicerBridge()

# New hardware drivers (connect on startup; non-fatal if unavailable)
_stm32 = STM32Driver()
_gpio = GPIODriver()

# Register new blueprints
app.register_blueprint(motor_bp)
app.register_blueprint(laser_bp)
app.register_blueprint(led_bp)

# Inject drivers into blueprints
_init_motor_driver(_stm32)
_init_laser_driver(_gpio)
_init_led_driver(_gpio)

# Print queue:  {id: {id, name, gcode_b64, added_at, status}}
_print_queue: dict = {}

# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return send_from_directory(str(_WEB_DIR), "index.html")

# ---------------------------------------------------------------------------
# Scan endpoints
# ---------------------------------------------------------------------------

@app.route("/api/scan/start", methods=["POST"])
def scan_start():
    _scan_session.start()
    return jsonify({"ok": True})


@app.route("/api/scan/stop", methods=["POST"])
def scan_stop():
    _scan_session.stop()
    return jsonify({"ok": True})


@app.route("/api/scan/status", methods=["GET"])
def scan_status():
    return jsonify(_scan_session.status())


@app.route("/api/scan/pointcloud", methods=["GET"])
def scan_pointcloud():
    return jsonify(_scan_session.get_pointcloud())

# ---------------------------------------------------------------------------
# Movement endpoints
# ---------------------------------------------------------------------------

def _safe_error(exc: Exception, context: str = "") -> str:
    """Return a sanitized error string that does not expose internal paths or stack traces."""
    logger.error("%s error: %s", context, exc)
    return f"{context} error" if context else "Internal error"


def _legacy_error_response(exc: Exception, *, bad_request: bool = False, message: str = "Hardware request failed"):
    status = 400 if bad_request else 503
    logger.error("Legacy hardware route error: %s", exc)
    return jsonify({"ok": False, "error": message}), status


def _legacy_turntable_mm_from_degrees(degrees: float) -> float:
    if not math.isfinite(degrees):
        raise ValueError("degrees must be a finite number")
    full_rotation_mm = float(_hardware_cfg.get("motors", {}).get("y", {}).get("position_max", 628.32))
    return (degrees / 360.0) * full_rotation_mm


def _motor_driver_required():
    try:
        _stm32.ensure_connected()
        return _stm32
    except ConnectionError as exc:
        raise ConnectionError(str(exc)) from exc


@app.route("/api/move/<axis>", methods=["POST"])
def move_axis(axis: str):
    axis = axis.upper()
    if axis not in ("X", "Y", "Z"):
        return jsonify({"ok": False, "error": "Invalid axis"}), 400
    data = request.get_json(silent=True) or {}
    try:
        mm = float(data.get("mm", 10))
        result = _motor_driver_required().motor_move(axis, mm)
        return jsonify({"ok": True, "legacy": True, **result})
    except ValueError as exc:
        return _legacy_error_response(exc, bad_request=True, message="Invalid axis move request")
    except (RuntimeError, ConnectionError) as exc:
        return _legacy_error_response(exc, message="Axis move failed")


@app.route("/api/rotate", methods=["POST"])
def rotate():
    data = request.get_json(silent=True) or {}
    try:
        degrees = float(data.get("degrees", 10))
        distance_mm = _legacy_turntable_mm_from_degrees(degrees)
        result = _motor_driver_required().motor_move("Y", distance_mm)
        return jsonify({"ok": True, "legacy": True, "degrees": degrees, **result})
    except ValueError as exc:
        return _legacy_error_response(exc, bad_request=True, message="Invalid rotate request")
    except (RuntimeError, ConnectionError) as exc:
        return _legacy_error_response(exc, message="Rotation failed")


@app.route("/api/home/<target>", methods=["POST"])
def home(target: str):
    try:
        if target == "all":
            result = _motor_driver_required().motor_home_all()
        else:
            axis = target.upper()
            if axis not in ("X", "Y", "Z"):
                return jsonify({"ok": False, "error": "Invalid axis"}), 400
            result = _motor_driver_required().motor_home(axis)
        return jsonify({"ok": True, "legacy": True, "result": result})
    except (RuntimeError, ConnectionError) as exc:
        return _legacy_error_response(exc, message="Homing failed")

# ---------------------------------------------------------------------------
# Laser endpoints
# ---------------------------------------------------------------------------

@app.route("/api/laser/<side>", methods=["POST"])
def laser_control(side: str):
    if side not in ("left", "right"):
        return jsonify({"ok": False, "error": "side must be left or right"}), 400
    data = request.get_json(silent=True) or {}
    state = bool(data.get("state", False))
    target = getattr(_gpio, f"laser_{side}_{'on' if state else 'off'}")
    target()
    return jsonify({"ok": True, "legacy": True, "state": state, **_gpio.laser_status()})

# ---------------------------------------------------------------------------
# LIDAR endpoints
# ---------------------------------------------------------------------------

@app.route("/api/lidar/read", methods=["POST"])
def lidar_read():
    if not _lidar.connected:
        _lidar.connect()
    dist = _lidar.read_distance_mm()
    if dist is None:
        return jsonify({"error": "LIDAR read failed"}), 503
    return jsonify({"distance_mm": round(dist, 1)})


@app.route("/api/lidar/calibrate", methods=["POST"])
def lidar_calibrate():
    data = request.get_json(silent=True) or {}
    known = float(data.get("known_distance_mm", 300.0))
    if not _lidar.connected:
        _lidar.connect()
    offset = _lidar.calibrate(known_distance_mm=known)
    cfg = config_manager.load()
    cfg["scanner"]["lidar_offset_mm"] = offset
    config_manager.save(cfg)
    return jsonify({"ok": True, "offset_mm": offset})


@app.route("/api/lidar/<direction>", methods=["POST"])
def lidar_move(direction: str):
    if direction not in ("up", "down"):
        return jsonify({"error": "direction must be up or down"}), 400
    data = request.get_json(silent=True) or {}
    try:
        mm = float(data.get("mm", 5))
        mm = mm if direction == "up" else -mm
        result = _motor_driver_required().motor_move("Z", mm)
        return jsonify({"ok": True, **result})
    except ValueError as exc:
        logger.warning("Rejected lidar move request: %s", exc)
        return jsonify({"ok": False, "error": "Invalid lidar move request"}), 400
    except (RuntimeError, ConnectionError) as exc:
        logger.error("Lidar move failed: %s", exc)
        return jsonify({"ok": False, "error": "Lidar move failed"}), 503

# ---------------------------------------------------------------------------
# Camera endpoints
# ---------------------------------------------------------------------------

@app.route("/api/camera/stream", methods=["GET"])
def camera_stream():
    if not _logitech.is_open:
        _logitech.open()

    def generate():
        yield from _logitech.mjpeg_generator()

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/camera/<cam>", methods=["POST"])
def camera_capture(cam: str):
    if cam == "logi":
        if not _logitech.is_open:
            _logitech.open()
        jpeg_b64 = _logitech.capture_jpeg_b64()
    elif cam == "picam":
        if not _picam.is_open:
            _picam.open()
        jpeg_b64 = _picam.capture_jpeg_b64()
    else:
        return jsonify({"error": "cam must be logi or picam"}), 400
    return jsonify({"jpeg_b64": jpeg_b64})

# ---------------------------------------------------------------------------
# LED endpoints
# ---------------------------------------------------------------------------

@app.route("/api/led/color", methods=["POST"])
def led_color():
    data = request.get_json(silent=True) or {}
    try:
        r = int(data.get("r", 0))
        g = int(data.get("g", 0))
        b = int(data.get("b", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "r, g, b must be integers 0-255"}), 400
    if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
        return jsonify({"ok": False, "error": "r, g, b must be in range 0-255"}), 400
    _gpio.led_set_rgb(r, g, b)
    return jsonify({"ok": True, "legacy": True, **_gpio.led_status()})

# ---------------------------------------------------------------------------
# 3D Model endpoints
# ---------------------------------------------------------------------------

@app.route("/api/model/reconstruct", methods=["POST"])
def model_reconstruct():
    result = _reconstruction.reconstruct()
    return jsonify(result)


@app.route("/api/model/current", methods=["GET"])
def model_current():
    fmt = request.args.get("format", "stl").lower()
    data = _reconstruction.get_model(fmt)
    if data is None:
        return jsonify({"error": "No model available – run /api/model/reconstruct first"}), 404
    mime = "model/stl" if fmt == "stl" else "application/x-amf"
    return Response(data, mimetype=mime,
                    headers={"Content-Disposition": f'attachment; filename="model.{fmt}"'})


@app.route("/api/model/export", methods=["POST"])
def model_export():
    data = request.get_json(silent=True) or {}
    fmt = data.get("format", "stl").lower()
    model_bytes = _reconstruction.get_model(fmt)
    if model_bytes is None:
        return jsonify({"error": "No model available"}), 404
    return jsonify({
        "ok": True,
        "format": fmt,
        "data_b64": base64.b64encode(model_bytes).decode(),
        "size": len(model_bytes),
    })

# ---------------------------------------------------------------------------
# Slicer endpoints
# ---------------------------------------------------------------------------

@app.route("/api/slice", methods=["POST"])
def slice_model():
    data = request.get_json(silent=True) or {}
    model_b64 = data.get("model_data", "")
    if not model_b64:
        return jsonify({"error": "model_data is required"}), 400
    try:
        stl_bytes = base64.b64decode(model_b64)
    except Exception:
        return jsonify({"error": "Invalid base64 model_data"}), 400

    result = _slicer.slice_stl(
        stl_bytes,
        layer_height=float(data.get("layer_height", 0.2)),
        infill=int(data.get("infill", 20)),
        support=bool(data.get("support", False)),
        nozzle_temp=int(data.get("nozzle_temp", 200)),
    )
    return jsonify(result)


@app.route("/api/slice/preview", methods=["GET"])
def slice_preview():
    return jsonify({"info": "3D preview not yet implemented; load gcode in a slicer."})

# ---------------------------------------------------------------------------
# Print Queue endpoints
# ---------------------------------------------------------------------------

@app.route("/api/queue", methods=["GET"])
def queue_list():
    return jsonify(list(_print_queue.values()))


@app.route("/api/queue/add", methods=["POST"])
def queue_add():
    data = request.get_json(silent=True) or {}
    gcode_b64 = data.get("gcode_b64", "")
    name = data.get("name", f"print_{int(time.time())}.gcode")
    if not gcode_b64:
        return jsonify({"error": "gcode_b64 is required"}), 400
    item_id = str(uuid.uuid4())[:8]
    _print_queue[item_id] = {
        "id": item_id,
        "name": name,
        "gcode_b64": gcode_b64,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "pending",
    }
    return jsonify({"ok": True, "id": item_id})


@app.route("/api/queue/<item_id>/send", methods=["POST"])
def queue_send(item_id: str):
    item = _print_queue.get(item_id)
    if not item:
        return jsonify({"error": "Item not found"}), 404
    data = request.get_json(silent=True) or {}
    moonraker_url = data.get("moonraker_url") or _cfg.get("moonraker", {}).get("url", "")
    api_key = data.get("api_key") or _cfg.get("moonraker", {}).get("api_key", "")

    client = MoonrakerClient(url=moonraker_url, api_key=api_key)
    gcode_bytes = base64.b64decode(item["gcode_b64"])
    result = client.upload_and_print(gcode_bytes, item["name"])
    if result["ok"]:
        item["status"] = "sent"
    return jsonify(result)


@app.route("/api/queue/<item_id>/remove", methods=["POST"])
def queue_remove(item_id: str):
    if item_id not in _print_queue:
        return jsonify({"error": "Item not found"}), 404
    del _print_queue[item_id]
    return jsonify({"ok": True})


@app.route("/api/queue/<item_id>/preview", methods=["GET"])
def queue_preview(item_id: str):
    item = _print_queue.get(item_id)
    if not item:
        return jsonify({"error": "Item not found"}), 404
    return jsonify({"info": "Preview not yet implemented", "name": item["name"]})

# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------

@app.route("/api/settings", methods=["GET"])
def settings_get():
    cfg = config_manager.load()
    # Don't expose the full api_key in GET response
    safe = {k: dict(v) for k, v in cfg.items()}
    if safe.get("moonraker", {}).get("api_key"):
        safe["moonraker"]["api_key"] = "***"
    return jsonify(safe)


@app.route("/api/settings", methods=["POST"])
def settings_save():
    data = request.get_json(silent=True) or {}
    cfg = config_manager.load()
    for section in ("scanner", "slicer", "moonraker", "system"):
        if section in data:
            cfg[section].update(data[section])
    config_manager.save(cfg)
    global _cfg
    _cfg = cfg
    return jsonify({"ok": True})


@app.route("/api/moonraker/test", methods=["POST"])
def moonraker_test():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    key = data.get("key", "")
    client = MoonrakerClient(url=url, api_key=key)
    result = client.test_connection()
    return jsonify(result)

# ---------------------------------------------------------------------------
# System endpoints
# ---------------------------------------------------------------------------

@app.route("/api/temperature", methods=["GET"])
def temperature():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp_c = int(f.read().strip()) / 1000
        return jsonify({"temperature_c": round(temp_c, 1)})
    except Exception:
        return jsonify({"temperature_c": None})


@app.route("/api/status", methods=["GET"])
def status():
    scan_st = _scan_session.status()
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp_c = int(f.read().strip()) / 1000
    except Exception:
        temp_c = None

    import shutil
    disk = shutil.disk_usage("/")

    return jsonify({
        "ok": True,
        "scanning": scan_st["scanning"],
        "temperature_c": round(temp_c, 1) if temp_c else None,
        "disk_free_gb": round(disk.free / 1e9, 2),
        "disk_total_gb": round(disk.total / 1e9, 2),
        "lidar_connected": _lidar.connected,
        "logitech_open": _logitech.is_open,
        "picam_open": _picam.is_open,
        "slicer_available": _slicer.is_available(),
        "gpio_available": _gpio.hardware_available,
        "gpio_simulation": _gpio.simulation,
        "stm32_connected": _stm32.is_connected,
        "stm32_protocol": _stm32.protocol,
        "hardware": {
            "stm32": _stm32.hardware_status(),
            "gpio": _gpio.status(),
        },
    })


@app.route("/api/update", methods=["POST"])
def system_update():
    # Restrict to localhost-only to prevent unauthorized code execution
    remote = request.remote_addr
    if remote not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "error": "Update only allowed from localhost"}), 403
    repo_dir = str(_REPO_ROOT)
    try:
        pull = subprocess.run(
            ["git", "-C", repo_dir, "pull", "origin", "main"],
            capture_output=True, text=True, timeout=60,
        )
        pip_install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r",
             os.path.join(repo_dir, "requirements.txt"), "--quiet"],
            capture_output=True, text=True, timeout=120,
        )
        return jsonify({
            "ok": pull.returncode == 0,
            "git_output": pull.stdout + pull.stderr,
            "pip_output": pip_install.stdout + pip_install.stderr,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": _safe_error(exc, "update")})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cfg = config_manager.load()
    port = cfg.get("system", {}).get("port", 5000)
    log_level = cfg.get("system", {}).get("log_level", "INFO")
    logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))

    # Try to open cameras and LIDAR at startup (non-fatal if they fail)
    _logitech.open()
    _picam.open()
    _lidar.connect()
    _stm32.connect()

    logger.info("🚀 HoralScanner PRO API starting on port %d", port)
    logger.info("📍 Web UI: http://0.0.0.0:%d/", port)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
