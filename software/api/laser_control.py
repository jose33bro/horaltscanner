"""
Laser Control API - Flask Blueprint for laser endpoints.

Endpoints:
  POST /api/laser/left/on
  POST /api/laser/left/off
  POST /api/laser/right/on
  POST /api/laser/right/off
  GET  /api/laser/status
"""

import logging
from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

laser_bp = Blueprint("laser", __name__)

_gpio = None


def init_driver(gpio_driver) -> None:
    """Inject the shared GPIODriver instance."""
    global _gpio
    _gpio = gpio_driver


def _driver_required():
    if _gpio is None:
        return None, (jsonify({"ok": False, "error": "GPIO driver not initialised"}), 503)
    return _gpio, None


@laser_bp.route("/api/laser/left/on", methods=["POST"])
def laser_left_on():
    driver, err = _driver_required()
    if err:
        return err
    driver.laser_left_on()
    return jsonify({"ok": True, "laser": "left", "state": True, **driver.laser_status()})


@laser_bp.route("/api/laser/left/off", methods=["POST"])
def laser_left_off():
    driver, err = _driver_required()
    if err:
        return err
    driver.laser_left_off()
    return jsonify({"ok": True, "laser": "left", "state": False, **driver.laser_status()})


@laser_bp.route("/api/laser/right/on", methods=["POST"])
def laser_right_on():
    driver, err = _driver_required()
    if err:
        return err
    driver.laser_right_on()
    return jsonify({"ok": True, "laser": "right", "state": True, **driver.laser_status()})


@laser_bp.route("/api/laser/right/off", methods=["POST"])
def laser_right_off():
    driver, err = _driver_required()
    if err:
        return err
    driver.laser_right_off()
    return jsonify({"ok": True, "laser": "right", "state": False, **driver.laser_status()})


@laser_bp.route("/api/laser/status", methods=["GET"])
def laser_status():
    driver, err = _driver_required()
    if err:
        return err
    return jsonify({"ok": True, **driver.laser_status()})
