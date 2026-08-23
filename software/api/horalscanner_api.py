"""
HoralScanner PRO - Main REST API
Replaces creality_api.py with a complete implementation.

Run:  python software/api/horalscanner_api.py
      (or via systemd service)
"""

import base64
import logging
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

sys.path.insert(0, str(_API_DIR))

import config_manager
from scanner_engine import ReconstructionEngine, ScanSession
from camera_driver import LogitechCamera, PiCamera
from lidar_driver import LidarDriver
from slicer_bridge import SlicerBridge
from moonraker_client import MoonrakerClient

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

_scan_session = ScanSession()
_reconstruction = ReconstructionEngine(_scan_session)
_logitech = LogitechCamera(device_id=0)
_picam = PiCamera()
_lidar = LidarDriver(port="/dev/ttyUSB0")
_slicer = SlicerBridge()

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


def _send_gcode(cmd: str) -> str:
    """Send a raw G-code command to the Creality board via serial."""
    try:
        import serial
        port = _cfg.get("scanner", {}).get("serial_port", "/dev/ttyUSB1")
        with serial.Serial(port, 115200, timeout=2) as ser:
            ser.write((cmd + "\n").encode())
            time.sleep(0.05)
            resp = ser.read(ser.in_waiting or 64).decode(errors="replace").strip()
        return resp
    except Exception as exc:
        logger.error("send_gcode error: %s", exc)
        return "error: serial communication failed"


@app.route("/api/move/<axis>", methods=["POST"])
def move_axis(axis: str):
    axis = axis.upper()
    if axis not in ("X", "Y", "Z"):
        return jsonify({"error": "Invalid axis"}), 400
    data = request.get_json(silent=True) or {}
    mm = float(data.get("mm", 10))
    resp = _send_gcode(f"G91\nG1 {axis}{mm} F3000\nG90")
    return jsonify({"ok": True, "response": resp})


@app.route("/api/rotate", methods=["POST"])
def rotate():
    data = request.get_json(silent=True) or {}
    degrees = float(data.get("degrees", 10))
    resp = _send_gcode(f"M120 S{degrees}")
    return jsonify({"ok": True, "response": resp})


@app.route("/api/home/<target>", methods=["POST"])
def home(target: str):
    if target == "all":
        resp = _send_gcode("G28")
    else:
        axis = target.upper()
        if axis not in ("X", "Y", "Z"):
            return jsonify({"error": "Invalid axis"}), 400
        resp = _send_gcode(f"G28 {axis}")
    return jsonify({"ok": True, "response": resp})

# ---------------------------------------------------------------------------
# Laser endpoints
# ---------------------------------------------------------------------------

try:
    from gpiozero import LED as GpioLED
    _laser_left = GpioLED(17)
    _laser_right = GpioLED(27)
    _GPIO_OK = True
except Exception:
    _GPIO_OK = False
    _laser_left = None
    _laser_right = None


@app.route("/api/laser/<side>", methods=["POST"])
def laser_control(side: str):
    if side not in ("left", "right"):
        return jsonify({"error": "side must be left or right"}), 400
    data = request.get_json(silent=True) or {}
    state = bool(data.get("state", False))
    if _GPIO_OK:
        target = _laser_left if side == "left" else _laser_right
        if state:
            target.on()
        else:
            target.off()
    return jsonify({"ok": True, "gpio_available": _GPIO_OK, "state": state})

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
    mm = float(data.get("mm", 5))
    mm = mm if direction == "up" else -mm
    resp = _send_gcode(f"G91\nG1 Z{mm} F500\nG90")
    return jsonify({"ok": True, "response": resp})

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

try:
    from gpiozero import RGBLED
    _led = RGBLED(red=22, green=23, blue=24)
    _LED_OK = True
except Exception:
    _LED_OK = False
    _led = None


@app.route("/api/led/color", methods=["POST"])
def led_color():
    data = request.get_json(silent=True) or {}
    r = int(data.get("r", 0)) / 255
    g = int(data.get("g", 0)) / 255
    b = int(data.get("b", 0)) / 255
    if _LED_OK:
        _led.color = (r, g, b)
    return jsonify({"ok": True, "gpio_available": _LED_OK})

# ---------------------------------------------------------------------------
# 3D Model endpoints
# ---------------------------------------------------------------------------

@app.route("/api/model/reconstruct", methods=["GET"])
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
        "gpio_available": _GPIO_OK,
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

    logger.info("🚀 HoralScanner PRO API starting on port %d", port)
    logger.info("📍 Web UI: http://0.0.0.0:%d/", port)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
