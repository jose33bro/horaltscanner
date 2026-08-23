"""
Motor Control API - Flask Blueprint for motor movement endpoints.

Endpoints:
  POST /api/motor/x/move    body: {"distance": <mm>, "velocity": <mm/s>?}
  POST /api/motor/y/move    body: {"distance": <mm>, "velocity": <mm/s>?}
  POST /api/motor/z/move    body: {"distance": <mm>, "velocity": <mm/s>?}
  POST /api/motor/home      body: {"axis": "X"|"Y"|"Z"|"all"}?
  POST /api/motor/stop
  GET  /api/motor/status
"""

import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

motor_bp = Blueprint("motor", __name__)

# The STM32Driver instance is injected by the main application at startup.
_stm32 = None


def init_driver(stm32_driver) -> None:
    """Inject the shared STM32Driver instance."""
    global _stm32
    _stm32 = stm32_driver


def _driver_required():
    """Return (driver, None) or (None, error_response)."""
    if _stm32 is None:
        return None, (jsonify({"ok": False, "error": "STM32 driver not initialised"}), 503)
    try:
        _stm32.ensure_connected()
    except ConnectionError as exc:
        return None, (jsonify({"ok": False, "error": str(exc)}), 503)
    return _stm32, None


@motor_bp.route("/api/motor/<axis>/move", methods=["POST"])
def motor_move(axis: str):
    """Move the given axis by *distance* mm (relative)."""
    axis = axis.upper()
    if axis not in ("X", "Y", "Z"):
        return jsonify({"ok": False, "error": "Invalid axis"}), 400

    driver, err = _driver_required()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    try:
        distance = float(data.get("distance", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "distance must be a number"}), 400

    velocity = data.get("velocity")
    if velocity is not None:
        try:
            velocity = float(velocity)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "velocity must be a number"}), 400

    try:
        result = driver.motor_move(axis, distance, velocity)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except ConnectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    return jsonify({"ok": True, **result})


@motor_bp.route("/api/motor/home", methods=["POST"])
def motor_home():
    """Home one axis or all axes."""
    driver, err = _driver_required()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    axis = str(data.get("axis", "all")).upper()

    if axis == "ALL":
        try:
            result = driver.motor_home_all()
        except (RuntimeError, ConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 503
    elif axis in ("X", "Y", "Z"):
        try:
            result = driver.motor_home(axis)
        except (RuntimeError, ConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 503
    else:
        return jsonify({"ok": False, "error": "axis must be X, Y, Z or all"}), 400

    return jsonify({"ok": True, "axis": axis, "result": result})


@motor_bp.route("/api/motor/stop", methods=["POST"])
def motor_stop():
    """Emergency stop all motors."""
    driver, err = _driver_required()
    if err:
        return err

    try:
        result = driver.motor_stop()
    except (RuntimeError, ConnectionError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    return jsonify({"ok": True, **result})


@motor_bp.route("/api/motor/status", methods=["GET"])
def motor_status():
    """Return software-tracked motor positions and homing state."""
    driver, err = _driver_required()
    if err:
        return err

    status = driver.motor_status()
    return jsonify({"ok": True, **status})
