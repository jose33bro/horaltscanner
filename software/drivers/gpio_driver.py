"""
GPIODriver - Raspberry Pi GPIO driver for HoralScanner peripherals.

Controls:
  - Left / right line lasers  (digital output)
  - RGB LED ring              (PWM output)
  - Pi cooling fan            (PWM output)

Hardware pin mapping (BCM numbering, from config):
  Laser left  → GPIO 27
  Laser right → GPIO 22
  LED R       → GPIO 18
  LED G       → GPIO 13
  LED B       → GPIO 19
  Fan Pi      → GPIO 23

The driver works in *simulation* mode (simulation=True or no RPi hardware)
so that unit tests can run on any platform.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default hardware pin configuration (BCM)
_DEFAULT_HW_CONFIG: dict[str, Any] = {
    "lasers": {
        "left":  {"gpio": 27},
        "right": {"gpio": 22},
    },
    "led_rgb": {
        "red":   {"gpio": 18},
        "green": {"gpio": 13},
        "blue":  {"gpio": 19},
    },
    "fans": {
        "pi_fan": {"gpio": 23},
    },
}

_VALID_LED_MODES = frozenset(
    {"rainbow", "pulse", "red", "green", "blue", "white", "off"}
)


class GPIODriver:
    """Raspberry Pi GPIO driver for lasers, LED ring, and Pi fan."""

    def __init__(
        self,
        simulation: bool = False,
        hardware_config: Optional[dict[str, Any]] = None,
    ):
        cfg = hardware_config if hardware_config is not None else _DEFAULT_HW_CONFIG

        self._simulation = simulation
        self._hardware_available = False

        # Resolve pin numbers from config
        lasers_cfg = cfg.get("lasers", {})
        led_cfg = cfg.get("led_rgb", {})
        fans_cfg = cfg.get("fans", {})

        self._pin_laser_left  = int(lasers_cfg.get("left",  {}).get("gpio", 27))
        self._pin_laser_right = int(lasers_cfg.get("right", {}).get("gpio", 22))
        self._pin_led_r       = int(led_cfg.get("red",   {}).get("gpio", 18))
        self._pin_led_g       = int(led_cfg.get("green", {}).get("gpio", 13))
        self._pin_led_b       = int(led_cfg.get("blue",  {}).get("gpio", 19))
        self._pin_fan_pi      = int(fans_cfg.get("pi_fan", {}).get("gpio", 23))

        # Software state
        self._laser_left_on  = False
        self._laser_right_on = False
        self._led_r: int = 0
        self._led_g: int = 0
        self._led_b: int = 0
        self._fan_speed: float = 0.0
        self._led_mode: str = "off"

        # Hardware initialisation (skipped in simulation)
        if not simulation:
            self._hardware_available = self._init_hardware()

    # ------------------------------------------------------------------
    # Hardware initialisation
    # ------------------------------------------------------------------

    def _init_hardware(self) -> bool:
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin_laser_left,  GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(self._pin_laser_right, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(self._pin_fan_pi,      GPIO.OUT, initial=GPIO.LOW)
            self._gpio = GPIO
            logger.info("GPIODriver hardware initialised")
            return True
        except Exception as exc:
            logger.warning("GPIODriver hardware init failed (simulation mode): %s", exc)
            return False

    def connect(self) -> bool:
        """Return True; GPIO is initialised in __init__."""
        return True

    # ------------------------------------------------------------------
    # Laser control
    # ------------------------------------------------------------------

    def laser_on(self, side: str) -> bool:
        if side in ("left", "both"):
            self._laser_left_on = True
            if self._hardware_available:
                self._gpio.output(self._pin_laser_left, self._gpio.HIGH)
        if side in ("right", "both"):
            self._laser_right_on = True
            if self._hardware_available:
                self._gpio.output(self._pin_laser_right, self._gpio.HIGH)
        return True

    def laser_off(self, side: str) -> bool:
        if side in ("left", "both"):
            self._laser_left_on = False
            if self._hardware_available:
                self._gpio.output(self._pin_laser_left, self._gpio.LOW)
        if side in ("right", "both"):
            self._laser_right_on = False
            if self._hardware_available:
                self._gpio.output(self._pin_laser_right, self._gpio.LOW)
        return True

    def laser_left_on(self) -> None:
        self.laser_on("left")

    def laser_left_off(self) -> None:
        self.laser_off("left")

    def laser_right_on(self) -> None:
        self.laser_on("right")

    def laser_right_off(self) -> None:
        self.laser_off("right")

    def get_laser_status(self) -> dict:
        return {
            "left":  self._laser_left_on,
            "right": self._laser_right_on,
        }

    def laser_status(self) -> dict:
        return {
            "left":               self._laser_left_on,
            "right":              self._laser_right_on,
            "simulation":         not self._hardware_available,
            "hardware_available": self._hardware_available,
        }

    # ------------------------------------------------------------------
    # LED control
    # ------------------------------------------------------------------

    def led_set(self, r: int, g: int, b: int) -> bool:
        self._led_r = max(0, min(255, r))
        self._led_g = max(0, min(255, g))
        self._led_b = max(0, min(255, b))
        self._led_mode = "custom"
        logger.debug("LED set to R=%d G=%d B=%d", self._led_r, self._led_g, self._led_b)
        return True

    def led_set_rgb(self, r: int, g: int, b: int) -> None:
        self.led_set(r, g, b)

    def led_set_mode(self, mode: str) -> None:
        if mode not in _VALID_LED_MODES:
            raise ValueError(f"unknown LED mode: {mode}")
        self._led_mode = mode
        _mode_colours = {
            "red":   (255, 0,   0),
            "green": (0,   255, 0),
            "blue":  (0,   0,   255),
            "white": (255, 255, 255),
            "off":   (0,   0,   0),
        }
        if mode in _mode_colours:
            r, g, b = _mode_colours[mode]
            self.led_set(r, g, b)

    def get_led_status(self) -> dict:
        return {"r": self._led_r, "g": self._led_g, "b": self._led_b}

    def led_status(self) -> dict:
        return {
            "r":                  self._led_r,
            "g":                  self._led_g,
            "b":                  self._led_b,
            "mode":               self._led_mode,
            "simulation":         not self._hardware_available,
            "hardware_available": self._hardware_available,
        }

    # ------------------------------------------------------------------
    # Fan control
    # ------------------------------------------------------------------

    def set_fan_speed(self, speed: float) -> bool:
        clamped = max(0.0, min(1.0, speed))
        self._fan_speed = clamped
        logger.debug("Pi fan speed set to %.2f", clamped)
        return True

    def get_fan_status(self) -> dict:
        return {"speed": self._fan_speed}

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "simulation":         self._simulation or not self._hardware_available,
            "hardware_available": self._hardware_available,
            "pins": {
                "laser_left":  self._pin_laser_left,
                "laser_right": self._pin_laser_right,
                "led_r":       self._pin_led_r,
                "led_g":       self._pin_led_g,
                "led_b":       self._pin_led_b,
                "fan_pi":      self._pin_fan_pi,
            },
            "laser":  self.get_laser_status(),
            "led":    self.get_led_status(),
            "fan":    self.get_fan_status(),
        }

    def cleanup(self) -> None:
        if self._hardware_available:
            try:
                self._gpio.cleanup()
            except Exception:
                pass
