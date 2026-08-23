"""
LED Control API - Flask Blueprint for RGB LED endpoints.

Endpoints:
  POST /api/led/set   body: {"r": 0-255, "g": 0-255, "b": 0-255}
  POST /api/led/mode  body: {"mode": "rainbow"|"pulse"|"red"|"green"|"blue"|"white"|"off"}
  GET  /api/led/status
"""

import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

led_bp = Blueprint("led", __name__)

_gpio = None


def init_driver(gpio_driver) -> None:
    """Inject the shared GPIODriver instance."""
    global _gpio
    _gpio = gpio_driver


def _driver_required():
    if _gpio is None:
        return None, (jsonify({"ok": False, "error": "GPIO driver not initialised"}), 503)
    return _gpio, None


@led_bp.route("/api/led/set", methods=["POST"])
def led_set():
    """Set LED to an explicit RGB colour (0–255 per channel)."""
    driver, err = _driver_required()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    try:
        r = int(data.get("r", 0))
        g = int(data.get("g", 0))
        b = int(data.get("b", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "r, g, b must be integers 0-255"}), 400

    if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
        return jsonify({"ok": False, "error": "r, g, b must be in range 0-255"}), 400

    driver.led_set_rgb(r, g, b)
    return jsonify({"ok": True, **driver.led_status()})


@led_bp.route("/api/led/mode", methods=["POST"])
def led_mode():
    """Apply a named colour mode (rainbow, pulse, red, green, blue, white, off)."""
    driver, err = _driver_required()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "off"))
    try:
        driver.led_set_mode(mode)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "mode": mode, **driver.led_status()})


@led_bp.route("/api/led/status", methods=["GET"])
def led_status():
    """Return current LED colour."""
    driver, err = _driver_required()
    if err:
        return err
    return jsonify({"ok": True, **driver.led_status()})
