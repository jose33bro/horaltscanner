"""
HoralScanner main Flask API.
Replaces creality_api.py with full scanner control + 3D reconstruction + slicing + Moonraker.
"""

import base64
import io
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

# Local modules
from klipper_client import KlipperClient, MoonrakerClient, load_settings, save_settings
from scanner_engine import ScannerEngine
from camera_driver import LogitechCamera, PiCamera
from lidar_driver import LidarDriver
from slicer_bridge import SlicerBridge, DEFAULT_PROFILE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Flask app
# ──────────────────────────────────────────────
WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
CORS(app)

# ──────────────────────────────────────────────
# Singletons
# ──────────────────────────────────────────────
_settings: Dict[str, Any] = load_settings()

klipper = KlipperClient(
    port=_settings.get("klipper_port", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"),
    baud=int(_settings.get("klipper_baud", 115200)),
)
moonraker = MoonrakerClient(
    base_url=_settings.get("moonraker_url", ""),
    api_token=_settings.get("moonraker_token", ""),
)
scanner_engine = ScannerEngine()
logi_cam = LogitechCamera(device_id=int(_settings.get("logi_device_id", 0)))
pi_cam = PiCamera()
lidar = LidarDriver(port=_settings.get("lidar_port", "/dev/ttyUSB0"))
slicer = SlicerBridge()

# In-memory print queue and model store
_print_queue: List[Dict[str, Any]] = []
_current_model: Dict[str, Any] = {"stl": None, "amf": None}
_scan_thread: Optional[threading.Thread] = None

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _klipper_cmd(cmd_fn, *args, **kwargs):
    """Call a Klipper command, auto-connect if needed."""
    if not klipper.connected:
        klipper.connect()
    if not klipper.connected:
        return {"error": "Klipper not connected"}, 503
    try:
        result = cmd_fn(*args, **kwargs)
        return {"ok": True, "response": result}
    except Exception as exc:
        logger.warning("Klipper command error: %s", exc)
        return {"error": "Klipper command failed"}, 500


def _json_ok(**kwargs) -> Response:
    return jsonify({"ok": True, **kwargs})


# ──────────────────────────────────────────────
# Static / SPA
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


# ──────────────────────────────────────────────
# System status
# ──────────────────────────────────────────────

@app.route("/api/status")
def system_status():
    return jsonify({
        "klipper_connected": klipper.connected,
        "scanning": scanner_engine.scanning,
        "scan_points": scanner_engine.buffer.count(),
        "slicer_available": slicer.available(),
        "moonraker_url": _settings.get("moonraker_url", ""),
        "queue_length": len(_print_queue),
    })


@app.route("/api/temperature")
def get_temperature():
    data = _klipper_cmd(klipper.get_temperature)
    return jsonify(data)


# ──────────────────────────────────────────────
# Axes / motion
# ──────────────────────────────────────────────

@app.route("/api/home/<axis>", methods=["POST"])
def home_axis(axis: str):
    if axis == "all":
        data = _klipper_cmd(klipper.home_all)
    else:
        data = _klipper_cmd(klipper.home_axis, axis)
    return jsonify(data)


@app.route("/api/move/x", methods=["POST"])
def move_x():
    mm = float(request.json.get("mm", 0))
    return jsonify(_klipper_cmd(klipper.move, "X", mm))


@app.route("/api/move/y", methods=["POST"])
def move_y():
    mm = float(request.json.get("mm", 0))
    return jsonify(_klipper_cmd(klipper.move, "Y", mm))


@app.route("/api/move/z", methods=["POST"])
def move_z():
    mm = float(request.json.get("mm", 0))
    return jsonify(_klipper_cmd(klipper.move, "Z", mm))


@app.route("/api/rotate", methods=["POST"])
def rotate():
    deg = float(request.json.get("degrees", 0))
    return jsonify(_klipper_cmd(klipper.rotate_deg, deg))


# ──────────────────────────────────────────────
# Lasers
# ──────────────────────────────────────────────

@app.route("/api/laser/<side>", methods=["POST"])
def laser_control(side: str):
    state = request.json.get("state", False)
    if side not in ("left", "right"):
        return jsonify({"error": "Invalid laser side"}), 400
    if state:
        data = _klipper_cmd(klipper.laser_on, side)
    else:
        data = _klipper_cmd(klipper.laser_off, side)
    return jsonify(data)


# ──────────────────────────────────────────────
# LIDAR
# ──────────────────────────────────────────────

@app.route("/api/lidar/read", methods=["POST", "GET"])
def lidar_read():
    # Try hardware first, fall back to Klipper macro
    dist = lidar.read_distance_mm()
    if dist is not None:
        return jsonify({"ok": True, "distance_mm": dist})
    # Fallback: parse Klipper READ_LIDAR response
    data = _klipper_cmd(klipper.read_lidar)
    if isinstance(data, tuple):
        return jsonify(data[0]), data[1]
    raw = data.get("response", "")
    dist_klipper = None
    for token in str(raw).split():
        if token.startswith("distance="):
            try:
                dist_klipper = float(token.split("=")[1])
            except ValueError:
                pass
    return jsonify({"ok": True, "distance_mm": dist_klipper, "raw": raw})


@app.route("/api/lidar/calibrate", methods=["POST"])
def lidar_calibrate():
    return jsonify(_klipper_cmd(klipper.lidar_calibrate))


# ──────────────────────────────────────────────
# LED / RGB
# ──────────────────────────────────────────────

@app.route("/api/led/color", methods=["POST"])
def led_color():
    body = request.json or {}
    r = int(body.get("r", 0))
    g = int(body.get("g", 0))
    b = int(body.get("b", 0))
    # Support hex
    hex_color = body.get("hex", "")
    if hex_color:
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    return jsonify(_klipper_cmd(klipper.set_rgb, r, g, b))


# ──────────────────────────────────────────────
# Camera
# ──────────────────────────────────────────────

@app.route("/api/camera/<cam>", methods=["POST"])
def capture_camera(cam: str):
    if cam == "picam":
        jpeg = pi_cam.capture_jpeg()
        _klipper_cmd(klipper.capture_picam)
    elif cam == "logi":
        jpeg = logi_cam.capture_jpeg()
        _klipper_cmd(klipper.capture_logi)
    else:
        return jsonify({"error": "Unknown camera"}), 400

    if jpeg is None:
        return jsonify({"ok": False, "error": "Capture failed"})
    b64 = base64.b64encode(jpeg).decode()
    return jsonify({"ok": True, "jpeg_b64": b64})


@app.route("/api/camera/stream")
def camera_stream():
    """MJPEG dual-camera stream (Logitech only for now)."""
    def generate():
        while True:
            jpeg = logi_cam.capture_jpeg()
            if jpeg is None:
                time.sleep(0.1)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + jpeg + b"\r\n"
            )
            time.sleep(0.1)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ──────────────────────────────────────────────
# Scanning
# ──────────────────────────────────────────────

@app.route("/api/scan/start", methods=["POST"])
def scan_start():
    global _scan_thread
    if scanner_engine.scanning:
        return jsonify({"ok": False, "error": "Already scanning"})
    scanner_engine.start()

    def _scan_worker():
        """Automated scan: rotate 360°, capture every degree."""
        try:
            _klipper_cmd(klipper.home_all)
            for angle in range(0, 360, 2):
                if not scanner_engine.scanning:
                    break
                _klipper_cmd(klipper.rotate_deg, 2)
                _klipper_cmd(klipper.laser_on, "left")
                _klipper_cmd(klipper.laser_on, "right")
                logi_frame = logi_cam.capture_frame()
                pi_frame = pi_cam.capture_frame()
                _klipper_cmd(klipper.laser_off, "left")
                _klipper_cmd(klipper.laser_off, "right")
                if logi_frame is not None:
                    scanner_engine.ingest_laser_frame(logi_frame, float(angle), pi_frame)
                # Read LIDAR distance
                dist = lidar.read_distance_mm()
                if dist is not None:
                    scanner_engine.buffer.add_point(
                        x=0.0, y=dist * 0.001, z=float(angle)
                    )
                time.sleep(0.05)
        finally:
            scanner_engine.stop()
            # Auto-reconstruct
            stl = scanner_engine.export_stl()
            amf = scanner_engine.export_amf()
            _current_model["stl"] = stl
            _current_model["amf"] = amf

    _scan_thread = threading.Thread(target=_scan_worker, daemon=True)
    _scan_thread.start()
    return _json_ok(message="Scan started")


@app.route("/api/scan/stop", methods=["POST"])
def scan_stop():
    scanner_engine.stop()
    return _json_ok(message="Scan stopped")


@app.route("/api/scan/status")
def scan_status():
    return jsonify(scanner_engine.status())


@app.route("/api/scan/pointcloud")
def scan_pointcloud():
    return jsonify(scanner_engine.buffer.to_dict())


# ──────────────────────────────────────────────
# 3D Model
# ──────────────────────────────────────────────

@app.route("/api/model/reconstruct")
def model_reconstruct():
    stl = scanner_engine.export_stl()
    amf = scanner_engine.export_amf()
    _current_model["stl"] = stl
    _current_model["amf"] = amf
    if stl is None:
        return jsonify({"ok": False, "error": "Reconstruction failed – too few points?"})
    return _json_ok(stl_size=len(stl), amf_size=len(amf) if amf else 0)


@app.route("/api/model/current")
def model_current():
    fmt = request.args.get("format", "stl").lower()
    data = _current_model.get(fmt)
    if data is None:
        return jsonify({"error": "No model available"}), 404
    mime = "model/stl" if fmt == "stl" else "model/amf"
    return Response(data, mimetype=mime,
                    headers={"Content-Disposition": f"inline; filename=model.{fmt}"})


@app.route("/api/model/export", methods=["POST"])
def model_export():
    fmt = (request.json or {}).get("format", "stl").lower()
    data = _current_model.get(fmt)
    if data is None:
        return jsonify({"error": "No model available"}), 404
    mime = "model/stl" if fmt == "stl" else "model/amf"
    return Response(
        data,
        mimetype=mime,
        headers={"Content-Disposition": f"attachment; filename=model.{fmt}"},
    )


# ──────────────────────────────────────────────
# Slicing
# ──────────────────────────────────────────────

@app.route("/api/slice", methods=["POST"])
def slice_model():
    body = request.json or {}
    fmt = body.get("format", "stl").lower()
    profile_overrides = body.get("profile", {})

    # Accept uploaded bytes or use current model
    model_b64 = body.get("model_b64")
    if model_b64:
        model_bytes = base64.b64decode(model_b64)
    else:
        model_bytes = _current_model.get(fmt)
    if not model_bytes:
        return jsonify({"error": "No model to slice"}), 400

    result = slicer.slice_model(model_bytes, model_ext=fmt, profile=profile_overrides)
    if not result["ok"]:
        logger.warning("Slicing failed: %s", result.get("log", ""))
        return jsonify({"ok": False, "error": "Slicing failed"}), 500

    gcode = result["gcode"]
    gcode_id = str(uuid.uuid4())[:8]
    # Store in queue
    _print_queue.append({
        "id": gcode_id,
        "filename": f"scan_{gcode_id}.gcode",
        "gcode": gcode,
        "created_at": time.time(),
        "status": "ready",
    })
    return _json_ok(gcode_id=gcode_id, size=len(gcode))


@app.route("/api/slice/preview")
def slice_preview():
    return jsonify({"message": "3D preview not yet implemented – use queue viewer"})


# ──────────────────────────────────────────────
# Print queue
# ──────────────────────────────────────────────

@app.route("/api/queue")
def queue_list():
    items = [
        {k: v for k, v in item.items() if k != "gcode"}
        for item in _print_queue
    ]
    return jsonify(items)


@app.route("/api/queue/add", methods=["POST"])
def queue_add():
    """Upload a G-code file to the queue."""
    if "file" in request.files:
        f = request.files["file"]
        gcode = f.read()
        filename = f.filename or "upload.gcode"
    else:
        body = request.json or {}
        gcode_b64 = body.get("gcode_b64", "")
        gcode = base64.b64decode(gcode_b64) if gcode_b64 else b""
        filename = body.get("filename", "upload.gcode")

    if not gcode:
        return jsonify({"error": "Empty G-code"}), 400

    item_id = str(uuid.uuid4())[:8]
    _print_queue.append({
        "id": item_id,
        "filename": filename,
        "gcode": gcode,
        "created_at": time.time(),
        "status": "ready",
    })
    return _json_ok(id=item_id, filename=filename)


@app.route("/api/queue/<item_id>/send", methods=["POST"])
def queue_send(item_id: str):
    item = next((i for i in _print_queue if i["id"] == item_id), None)
    if item is None:
        return jsonify({"error": "Not found"}), 404
    if not moonraker.base_url:
        return jsonify({"error": "Moonraker URL not configured"}), 400

    result = moonraker.upload_gcode(item["filename"], item["gcode"])
    if not result["ok"]:
        logger.warning("Moonraker upload failed: %s", result.get("error"))
        return jsonify({"error": "Upload to Moonraker failed"}), 500
    start_result = moonraker.start_print(item["filename"])
    item["status"] = "printing"
    return jsonify({"ok": True, "started": start_result.get("ok", False)})


@app.route("/api/queue/<item_id>/remove", methods=["POST"])
def queue_remove(item_id: str):
    global _print_queue
    _print_queue = [i for i in _print_queue if i["id"] != item_id]
    return _json_ok()


# ──────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def settings_get():
    safe = {k: v for k, v in _settings.items() if k != "moonraker_token"}
    safe["moonraker_token"] = "***" if _settings.get("moonraker_token") else ""
    return jsonify(safe)


@app.route("/api/settings", methods=["POST"])
def settings_save():
    global _settings
    body = request.json or {}
    # Keep existing token if placeholder sent
    if body.get("moonraker_token") == "***":
        body["moonraker_token"] = _settings.get("moonraker_token", "")
    _settings.update(body)
    save_settings(_settings)

    # Update live clients
    klipper.port = _settings.get("klipper_port", klipper.port)
    moonraker.base_url = _settings.get("moonraker_url", "")
    moonraker.api_token = _settings.get("moonraker_token", "")
    return _json_ok()


@app.route("/api/moonraker/test", methods=["POST"])
def moonraker_test():
    body = request.json or {}
    url = body.get("url") or moonraker.base_url
    token = body.get("token") or moonraker.api_token
    if not url:
        return jsonify({"ok": False, "error": "Moonraker URL not configured"})
    temp_client = MoonrakerClient(base_url=url, api_token=token)
    result = temp_client.test_connection()
    return jsonify(result)


# ──────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("🚀 HoralScanner API started")
    print("📍 http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
