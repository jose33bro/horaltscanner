"""Horaltscanner Flask API."""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, request

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


stm32_driver = STM32Driver() if STM32Driver else None
gpio_driver = GPIODriver() if GPIODriver else None

_initialize_driver(stm32_driver, "STM32Driver")
_initialize_driver(gpio_driver, "GPIODriver")


def _json_error(message: str, status_code: int = 400):
    return jsonify({"success": False, "error": message}), status_code


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
    except Exception as exc:
        return _json_error(str(exc), 500)


@app.route("/api/led/color", methods=["POST"])
def led_color():
    data = request.get_json(silent=True) or {}
    r = int(data.get("r", 0))
    g = int(data.get("g", 0))
    b = int(data.get("b", 0))

    if gpio_driver is None:
        return _json_error("GPIO driver unavailable", 503)

    try:
        success = gpio_driver.led_set(r, g, b)
        if not success:
            return _json_error("Failed to set LED color")

        return jsonify({"success": True, "status": gpio_driver.get_led_status()})
    except Exception as exc:
        return _json_error(str(exc), 500)


@app.route("/api/move/<axis>", methods=["POST"])
def move(axis: str):
    data = request.get_json(silent=True) or {}
    distance = float(data.get("mm", 0.0))

    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        success = stm32_driver.move_motor(axis, distance)
        if not success:
            return _json_error("Failed to move motor")

        return jsonify({"success": True, "status": stm32_driver.get_motor_status()})
    except Exception as exc:
        return _json_error(str(exc), 500)


@app.route("/api/home/<target>", methods=["POST"])
def home(target: str):
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        success = stm32_driver.home_motor(target)
        if not success:
            return _json_error("Failed to home motor")

        return jsonify({"success": True, "status": stm32_driver.get_motor_status()})
    except Exception as exc:
        return _json_error(str(exc), 500)


@app.route("/api/motor/status", methods=["GET", "POST"])
def motor_status():
    if stm32_driver is None:
        return _json_error("STM32 driver unavailable", 503)

    try:
        return jsonify({"success": True, "status": stm32_driver.get_motor_status()})
    except Exception as exc:
        return _json_error(str(exc), 500)


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
    except Exception as exc:
        return _json_error(str(exc), 500)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=5000)
