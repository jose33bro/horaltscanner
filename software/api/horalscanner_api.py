"""
HoralScanner API - REST API for 3D scanner hardware control
Hardware: X/Y/Z steppers, 2 lasers, USB+DSI cameras, TF-Luna LIDAR, LED RGB, temperature, fans
"""

from __future__ import annotations

import sys
from pathlib import Path

import threading

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

# Make software.app importable when running from repo root or directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from software.app.pi_hardware import LaserController, SensorRig
from software.app.scanner_controller import ScanController
from software.app.usb_driver import CrealityUsbDriver

# ---------------------------------------------------------------------------
# Physical limits (mm)
# ---------------------------------------------------------------------------
X_MAX_MM = 210.0
Y_MAX_MM = 628.32
Z_MAX_MM = 270.0

# Steps-per-mm conversion factors (adjust to match hardware calibration)
X_STEPS_PER_MM = 80.0
Y_STEPS_PER_MM = 80.0
Z_STEPS_PER_MM = 400.0

# GPIO pin assignments
LASER_LEFT_GPIO = 27
LASER_RIGHT_GPIO = 22
LED_R_GPIO = 18
LED_G_GPIO = 13
LED_B_GPIO = 19

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
WEB_DIR = str(Path(__file__).parent.parent / "web")

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
CORS(app)

# ---------------------------------------------------------------------------
# Hardware stubs / singletons
# A real deployment wires real transport; tests replace these via DI.
# ---------------------------------------------------------------------------


class _NullTransport:
    """Silent stub used when no real USB device is attached."""

    def write(self, payload: bytes) -> None:  # noqa: D401
        pass

    def read_line(self) -> bytes:
        return b"OK stub\n"


_usb = CrealityUsbDriver(transport=_NullTransport())
_lasers = LaserController(left_gpio_pin=LASER_LEFT_GPIO, right_gpio_pin=LASER_RIGHT_GPIO)
_sensors = SensorRig(
    lidar_port="/dev/ttyUSB0",
    usb_camera_id="logitech-0",
    dsi_camera_id="picam-v3",
)
_scanner = ScanController(usb=_usb, lasers=_lasers, sensors=_sensors)

# Thread safety lock for _state
_state_lock = threading.Lock()

# Runtime state (position tracking, LED state, fan state)
_state: dict = {
    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
    "lasers": {"left": False, "right": False},
    "led": {"r": 0, "g": 0, "b": 0},
    "fans": {"fan1": False, "fan2": False},
    "scan_active": False,
    "scan_progress": 0,
    "last_lidar_mm": None,
    "temperature": None,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _mm_to_steps(axis: str, mm: float) -> int:
    factor = {"x": X_STEPS_PER_MM, "y": Y_STEPS_PER_MM, "z": Z_STEPS_PER_MM}[axis.lower()]
    return round(mm * factor)


# ---------------------------------------------------------------------------
# Routes – static files
# ---------------------------------------------------------------------------


@app.route("/")
def index() -> Response:
    return send_from_directory(WEB_DIR, "index.html")


# ---------------------------------------------------------------------------
# Routes – status
# ---------------------------------------------------------------------------


@app.route("/api/status", methods=["GET"])
def api_status():
    """Global scanner status."""
    with _state_lock:
        snapshot = {
            "connected": True,
            "position": dict(_state["position"]),
            "lasers": dict(_state["lasers"]),
            "led": dict(_state["led"]),
            "fans": dict(_state["fans"]),
            "scan_active": _state["scan_active"],
            "scan_progress": _state["scan_progress"],
            "last_lidar_mm": _state["last_lidar_mm"],
            "temperature": _state["temperature"],
            "limits": {
                "x_max_mm": X_MAX_MM,
                "y_max_mm": Y_MAX_MM,
                "z_max_mm": Z_MAX_MM,
            },
        }
    return jsonify(snapshot)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Routes – axis movement
# ---------------------------------------------------------------------------


@app.route("/api/move", methods=["POST"])
def api_move():
    """Move one or more axes to absolute positions (mm)."""
    data = request.get_json(force=True) or {}
    with _state_lock:
        for axis, max_mm in (("x", X_MAX_MM), ("y", Y_MAX_MM), ("z", Z_MAX_MM)):
            if axis in data:
                mm = _clamp(float(data[axis]), 0.0, max_mm)
                steps = _mm_to_steps(axis, mm)
                speed = int(data.get("speed", 400))
                try:
                    _usb.move(axis, steps, speed)
                except RuntimeError:
                    pass  # stub / offline hardware
                _state["position"][axis] = mm
        position = dict(_state["position"])
    return jsonify({"status": "moved", "position": position})


@app.route("/api/move/x", methods=["POST"])
def api_move_x():
    data = request.get_json(force=True) or {}
    mm = _clamp(float(data.get("mm", 0)), 0.0, X_MAX_MM)
    speed = int(data.get("speed", 400))
    steps = _mm_to_steps("x", mm)
    try:
        _usb.move("X", steps, speed)
    except RuntimeError:
        pass
    with _state_lock:
        _state["position"]["x"] = mm
    return jsonify({"status": "moved", "axis": "x", "mm": mm})


@app.route("/api/move/y", methods=["POST"])
def api_move_y():
    data = request.get_json(force=True) or {}
    mm = _clamp(float(data.get("mm", 0)), 0.0, Y_MAX_MM)
    speed = int(data.get("speed", 300))
    steps = _mm_to_steps("y", mm)
    try:
        _usb.move("Y", steps, speed)
    except RuntimeError:
        pass
    with _state_lock:
        _state["position"]["y"] = mm
    return jsonify({"status": "moved", "axis": "y", "mm": mm})


@app.route("/api/move/z", methods=["POST"])
def api_move_z():
    data = request.get_json(force=True) or {}
    mm = _clamp(float(data.get("mm", 0)), 0.0, Z_MAX_MM)
    speed = int(data.get("speed", 200))
    steps = _mm_to_steps("z", mm)
    try:
        _usb.move("Z", steps, speed)
    except RuntimeError:
        pass
    with _state_lock:
        _state["position"]["z"] = mm
    return jsonify({"status": "moved", "axis": "z", "mm": mm})


@app.route("/api/home", methods=["POST"])
def api_home():
    """Home Y axis to LIDAR zero and reset position tracking."""
    try:
        _scanner.home_y_to_lidar_zero()
    except RuntimeError:
        pass
    with _state_lock:
        _state["position"].update({"x": 0.0, "y": 0.0, "z": 0.0})
        position = dict(_state["position"])
    return jsonify({"status": "homed", "position": position})


# ---------------------------------------------------------------------------
# Routes – laser control
# ---------------------------------------------------------------------------


@app.route("/api/laser", methods=["POST"])
def api_laser():
    """Set laser states. Body: {"left": true/false, "right": true/false}"""
    data = request.get_json(force=True) or {}
    left = bool(data.get("left", _state["lasers"]["left"]))
    right = bool(data.get("right", _state["lasers"]["right"]))
    with _state_lock:
        _lasers.set_state(left, right)
        _state["lasers"].update({"left": left, "right": right})
        lasers = dict(_state["lasers"])
    return jsonify({"status": "ok", "lasers": lasers})


@app.route("/api/laser/left", methods=["POST"])
def api_laser_left():
    data = request.get_json(force=True) or {}
    on = bool(data.get("on", False))
    with _state_lock:
        _lasers.set_state(on, _state["lasers"]["right"])
        _state["lasers"]["left"] = on
        lasers = dict(_state["lasers"])
    return jsonify({"status": "ok", "lasers": lasers})


@app.route("/api/laser/right", methods=["POST"])
def api_laser_right():
    data = request.get_json(force=True) or {}
    on = bool(data.get("on", False))
    with _state_lock:
        _lasers.set_state(_state["lasers"]["left"], on)
        _state["lasers"]["right"] = on
        lasers = dict(_state["lasers"])
    return jsonify({"status": "ok", "lasers": lasers})


# ---------------------------------------------------------------------------
# Routes – cameras
# ---------------------------------------------------------------------------


@app.route("/api/camera/capture", methods=["POST"])
def api_camera_capture():
    """Capture a frame from both cameras."""
    frame = _sensors.capture_frame()
    result = {
        "lidar_distance_mm": frame.get("lidar_distance_mm"),
        "usb_camera_available": frame.get("usb_camera_frame") is not None,
        "dsi_camera_available": frame.get("dsi_camera_frame") is not None,
    }
    if frame.get("lidar_distance_mm") is not None:
        with _state_lock:
            _state["last_lidar_mm"] = frame["lidar_distance_mm"]
    return jsonify(result)


@app.route("/api/camera/usb/capture", methods=["POST"])
def api_camera_usb():
    frame = _sensors.capture_frame()
    return jsonify(
        {
            "available": frame.get("usb_camera_frame") is not None,
            "lidar_distance_mm": frame.get("lidar_distance_mm"),
        }
    )


@app.route("/api/camera/dsi/capture", methods=["POST"])
def api_camera_dsi():
    frame = _sensors.capture_frame()
    return jsonify({"available": frame.get("dsi_camera_frame") is not None})


# ---------------------------------------------------------------------------
# Routes – LIDAR
# ---------------------------------------------------------------------------


@app.route("/api/lidar", methods=["GET"])
def api_lidar():
    """Read distance from TF-Luna LIDAR."""
    frame = _sensors.capture_frame()
    distance = frame.get("lidar_distance_mm")
    with _state_lock:
        _state["last_lidar_mm"] = distance
    return jsonify({"lidar_distance_mm": distance})


# ---------------------------------------------------------------------------
# Routes – LED RGB
# ---------------------------------------------------------------------------


@app.route("/api/led", methods=["POST"])
def api_led():
    """Set LED RGB values (0-255). Body: {"r": int, "g": int, "b": int}"""
    data = request.get_json(force=True) or {}
    r = int(_clamp(float(data.get("r", 0)), 0, 255))
    g = int(_clamp(float(data.get("g", 0)), 0, 255))
    b = int(_clamp(float(data.get("b", 0)), 0, 255))
    # GPIO LED control integration point (gpiozero/RPi.GPIO)
    with _state_lock:
        _state["led"].update({"r": r, "g": g, "b": b})
        led = dict(_state["led"])
    return jsonify({"status": "ok", "led": led})


@app.route("/api/led/off", methods=["POST"])
def api_led_off():
    with _state_lock:
        _state["led"].update({"r": 0, "g": 0, "b": 0})
        led = dict(_state["led"])
    return jsonify({"status": "off", "led": led})


# ---------------------------------------------------------------------------
# Routes – fans / temperature
# ---------------------------------------------------------------------------


@app.route("/api/fan", methods=["POST"])
def api_fan():
    """Control cooling fans. Body: {"fan1": true/false, "fan2": true/false}"""
    data = request.get_json(force=True) or {}
    with _state_lock:
        if "fan1" in data:
            _state["fans"]["fan1"] = bool(data["fan1"])
        if "fan2" in data:
            _state["fans"]["fan2"] = bool(data["fan2"])
        fans = dict(_state["fans"])
    return jsonify({"status": "ok", "fans": fans})


@app.route("/api/temperature", methods=["GET"])
def api_temperature():
    """Read board temperature sensor."""
    # Integration point: real hardware reads from I2C/one-wire sensor
    return jsonify({"temperature_c": _state["temperature"]})


# ---------------------------------------------------------------------------
# Routes – scan acquisition
# ---------------------------------------------------------------------------


@app.route("/api/scan/step", methods=["POST"])
def api_scan_step():
    """Acquire a single scan step (move X, fire lasers, capture frame)."""
    data = request.get_json(force=True) or {}
    x_mm = _clamp(float(data.get("x_mm", 0)), 0.0, X_MAX_MM)
    sync_token = str(data.get("sync_token", "step0"))
    x_steps = _mm_to_steps("x", x_mm)
    try:
        payload = _scanner.acquire_scan_step(x_steps, sync_token)
        with _state_lock:
            _state["position"]["x"] = x_mm
            if payload.get("lidar_distance_mm") is not None:
                _state["last_lidar_mm"] = payload["lidar_distance_mm"]
        return jsonify(
            {
                "status": "ok",
                "x_mm": x_mm,
                "sync": payload.get("sync"),
                "lidar_distance_mm": payload.get("lidar_distance_mm"),
                "usb_camera_available": payload.get("usb_camera_frame") is not None,
                "dsi_camera_available": payload.get("dsi_camera_frame") is not None,
            }
        )
    except RuntimeError:
        return jsonify({"status": "error", "message": "Scan step failed"}), 500


@app.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    """Begin a full scan sequence."""
    with _state_lock:
        if _state["scan_active"]:
            return jsonify({"status": "error", "message": "Scan already active"}), 409
        _state["scan_active"] = True
        _state["scan_progress"] = 0
    return jsonify({"status": "started"})


@app.route("/api/scan/stop", methods=["POST"])
def api_scan_stop():
    """Abort an active scan."""
    with _state_lock:
        _state["scan_active"] = False
        _state["scan_progress"] = 0
    return jsonify({"status": "stopped"})


@app.route("/api/scan/progress", methods=["GET"])
def api_scan_progress():
    with _state_lock:
        data = {
            "scan_active": _state["scan_active"],
            "scan_progress": _state["scan_progress"],
            "position": dict(_state["position"]),
        }
    return jsonify(data)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        print("🚀 HoralScanner API started")
        print("📍 http://0.0.0.0:5000")
        app.run(host="0.0.0.0", port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n✓ Arrêt")
