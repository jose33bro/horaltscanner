"""
GPIO Driver - Raspberry Pi GPIO control for HoralScanner.

Controls (all BCM pin numbers, from printer.cfg / hardware config):
  - Laser left:  GPIO27
  - Laser right: GPIO22
  - LED RGB:     R=GPIO18, G=GPIO13, B=GPIO19  (PWM)
  - Pi fan:      GPIO23                         (PWM)

Uses gpiozero library; falls back to simulation mode when not available
(e.g., when running on a development machine).
"""

import logging
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pin definitions (BCM, from printer.cfg)
# ---------------------------------------------------------------------------

PIN_LASER_LEFT = 27
PIN_LASER_RIGHT = 22
PIN_LED_R = 18
PIN_LED_G = 13
PIN_LED_B = 19
PIN_FAN_PI = 23

# ---------------------------------------------------------------------------
# Try to import gpiozero
# ---------------------------------------------------------------------------

try:
    from gpiozero import LED as _GpioLED, PWMOutputDevice as _PWM
    _GPIOZERO_AVAILABLE = True
except Exception:
    _GPIOZERO_AVAILABLE = False
    logger.warning("gpiozero not available – GPIO driver running in simulation mode")


class GPIODriver:
    """
    High-level GPIO driver for lasers, LED RGB, and the Pi fan.

    Instantiate with ``simulation=True`` to skip real hardware
    (automatic when gpiozero is not installed).
    """

    def __init__(self, simulation: bool = False):
        self._sim = simulation or not _GPIOZERO_AVAILABLE

        self._laser_left: Optional[object] = None
        self._laser_right: Optional[object] = None
        self._led_r: Optional[object] = None
        self._led_g: Optional[object] = None
        self._led_b: Optional[object] = None
        self._fan: Optional[object] = None

        # Soft state (used both in simulation and to cache real state)
        self._laser_left_on = False
        self._laser_right_on = False
        self._rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._fan_speed: float = 0.0

        if not self._sim:
            self._init_gpio()

    def _init_gpio(self) -> None:
        """Initialise gpiozero device objects."""
        try:
            self._laser_left = _GpioLED(PIN_LASER_LEFT)
            self._laser_right = _GpioLED(PIN_LASER_RIGHT)
            self._led_r = _PWM(PIN_LED_R)
            self._led_g = _PWM(PIN_LED_G)
            self._led_b = _PWM(PIN_LED_B)
            self._fan = _PWM(PIN_FAN_PI)
            logger.info("GPIO driver initialised (hardware mode)")
        except Exception as exc:
            logger.error("GPIO init error: %s – falling back to simulation", exc)
            self._sim = True

    # ------------------------------------------------------------------
    # Laser control
    # ------------------------------------------------------------------

    def laser_left_on(self) -> None:
        """Turn the left laser (GPIO27) on."""
        self._laser_left_on = True
        if not self._sim and self._laser_left:
            self._laser_left.on()
        logger.debug("Laser left ON")

    def laser_left_off(self) -> None:
        """Turn the left laser off."""
        self._laser_left_on = False
        if not self._sim and self._laser_left:
            self._laser_left.off()
        logger.debug("Laser left OFF")

    def laser_right_on(self) -> None:
        """Turn the right laser (GPIO22) on."""
        self._laser_right_on = True
        if not self._sim and self._laser_right:
            self._laser_right.on()
        logger.debug("Laser right ON")

    def laser_right_off(self) -> None:
        """Turn the right laser off."""
        self._laser_right_on = False
        if not self._sim and self._laser_right:
            self._laser_right.off()
        logger.debug("Laser right OFF")

    def laser_status(self) -> dict:
        """Return current laser state."""
        return {
            "left": self._laser_left_on,
            "right": self._laser_right_on,
        }

    # ------------------------------------------------------------------
    # LED RGB control
    # ------------------------------------------------------------------

    def led_set_rgb(self, r: int, g: int, b: int) -> None:
        """
        Set LED RGB colour.

        *r*, *g*, *b* are 0–255 integers.
        """
        r_f = max(0.0, min(1.0, r / 255.0))
        g_f = max(0.0, min(1.0, g / 255.0))
        b_f = max(0.0, min(1.0, b / 255.0))
        self._rgb = (r_f, g_f, b_f)
        if not self._sim:
            if self._led_r:
                self._led_r.value = r_f
            if self._led_g:
                self._led_g.value = g_f
            if self._led_b:
                self._led_b.value = b_f
        logger.debug("LED RGB (%d, %d, %d)", r, g, b)

    def led_off(self) -> None:
        """Turn the LED off."""
        self.led_set_rgb(0, 0, 0)

    def led_set_mode(self, mode: str) -> None:
        """
        Apply a named colour mode (rainbow, pulse, red, green, blue, white, off).

        ``rainbow`` and ``pulse`` run in a background thread so they do not
        block the calling thread (e.g. a Flask worker).
        """
        mode = mode.lower()
        presets = {
            "red":   (255, 0,   0),
            "green": (0,   255, 0),
            "blue":  (0,   0,   255),
            "white": (255, 255, 255),
            "off":   (0,   0,   0),
        }
        if mode in presets:
            self.led_set_rgb(*presets[mode])
        elif mode == "pulse":
            threading.Thread(target=self._led_pulse_bg, daemon=True).start()
        elif mode == "rainbow":
            threading.Thread(target=self._led_rainbow_bg, daemon=True).start()
        else:
            logger.warning("Unknown LED mode: %s", mode)

    def _led_pulse_bg(self) -> None:
        """Background pulse animation (blue fade in/out)."""
        for v in range(0, 256, 16):
            self.led_set_rgb(0, 0, v)
            time.sleep(0.02)
        for v in range(255, -1, -16):
            self.led_set_rgb(0, 0, v)
            time.sleep(0.02)
        self.led_off()

    def _led_rainbow_bg(self) -> None:
        """Background rainbow animation."""
        for hue in range(0, 360, 10):
            r, g, b = _hsv_to_rgb(hue / 360.0, 1.0, 1.0)
            self.led_set_rgb(r, g, b)
            time.sleep(0.03)
        self.led_off()

    def led_status(self) -> dict:
        """Return current LED state."""
        r_f, g_f, b_f = self._rgb
        return {
            "r": round(r_f * 255),
            "g": round(g_f * 255),
            "b": round(b_f * 255),
        }

    # ------------------------------------------------------------------
    # Pi fan control
    # ------------------------------------------------------------------

    def fan_on(self, speed: float = 1.0) -> None:
        """Turn the Pi fan (GPIO23) on at *speed* (0.0–1.0)."""
        speed = max(0.0, min(1.0, speed))
        self._fan_speed = speed
        if not self._sim and self._fan:
            self._fan.value = speed
        logger.debug("Pi fan ON speed=%.2f", speed)

    def fan_off(self) -> None:
        """Turn the Pi fan off."""
        self._fan_speed = 0.0
        if not self._sim and self._fan:
            self._fan.value = 0.0
        logger.debug("Pi fan OFF")

    def fan_status(self) -> dict:
        """Return current fan state."""
        return {"speed": self._fan_speed, "on": self._fan_speed > 0}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Turn off all outputs."""
        self.laser_left_off()
        self.laser_right_off()
        self.led_off()
        self.fan_off()
        logger.info("GPIO driver shutdown")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    """Convert HSV (all 0–1) to RGB (0–255)."""
    import colorsys
    r_f, g_f, b_f = colorsys.hsv_to_rgb(h, s, v)
    return int(r_f * 255), int(g_f * 255), int(b_f * 255)
