"""HoralScanner Flask API."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

# Add repo root to path so 'software' module can be imported
_API_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _API_DIR.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from flask import Flask, jsonify, request, send_from_directory

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


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "success": True,
        "status": {
            "api": "ok",
            "gpio_driver": gpio_driver is not None,
            "stm32_driver": stm32_driver is not None,
            "version": _VERSION,
        },
    })



@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=5000, debug=False)
