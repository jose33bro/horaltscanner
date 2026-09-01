<<<<<<< HEAD
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
=======
"""GPIO driver for HoralScanner lasers, LED, and fans.

Supports a *simulation* mode (no hardware required) used by the test suite.
"""
from __future__ import annotations

from typing import Callable

_DEFAULT_HARDWARE_CONFIG: dict = {
    "lasers": {
        "left": {"gpio": 17, "active_high": True},
        "right": {"gpio": 27, "active_high": True},
    },
    "led_rgb": {
        "active_high": True,
        "pwm_frequency_hz": 100,
        "red": {"gpio": 22},
        "green": {"gpio": 23},
        "blue": {"gpio": 24},
    },
    "fans": {
        "pi_fan": {
            "gpio": 18,
            "active_high": True,
            "default_value": 0,
            "auto_control": False,
            "on_temp_c": 55,
            "off_temp_c": 45,
        }
    },
}

_LED_MODES = {"off", "on", "pulse"}


class GPIODriver:
    """GPIO driver with optional simulation mode."""

    def __init__(
        self,
        simulation: bool = False,
        hardware_config: dict | None = None,
        output_device_factory: Callable | None = None,
        pwm_device_factory: Callable | None = None,
        temperature_reader: Callable | None = None,
    ) -> None:
        cfg_in = hardware_config or {}

        lasers_cfg = cfg_in.get("lasers", _DEFAULT_HARDWARE_CONFIG["lasers"])
        led_cfg = cfg_in.get("led_rgb", _DEFAULT_HARDWARE_CONFIG["led_rgb"])
        fans_cfg = cfg_in.get("fans", _DEFAULT_HARDWARE_CONFIG["fans"])
        pi_fan_cfg: dict = fans_cfg.get("pi_fan", _DEFAULT_HARDWARE_CONFIG["fans"]["pi_fan"])

        on_temp = pi_fan_cfg.get("on_temp_c", 55)
        off_temp = pi_fan_cfg.get("off_temp_c", 45)
        if on_temp <= off_temp:
            raise ValueError(
                f"on_temp_c ({on_temp}) must be greater than off_temp_c ({off_temp})"
            )

        self._simulation = simulation
        self._hardware_config = dict(cfg_in)
        self._output_device_factory = output_device_factory
        self._pwm_device_factory = pwm_device_factory
        self._temperature_reader = temperature_reader

        self._pin_laser_left: int = lasers_cfg.get("left", {}).get("gpio", 17)
        self._pin_laser_right: int = lasers_cfg.get("right", {}).get("gpio", 27)
        self._pin_led_r: int = led_cfg.get("red", {}).get("gpio", 22)
        self._pin_led_g: int = led_cfg.get("green", {}).get("gpio", 23)
        self._pin_led_b: int = led_cfg.get("blue", {}).get("gpio", 24)
        self._pin_fan_pi: int = pi_fan_cfg.get("gpio", 18)

        self._pi_fan_on_temp: float = float(on_temp)
        self._pi_fan_off_temp: float = float(off_temp)
        self._pi_fan_auto: bool = pi_fan_cfg.get("auto_control", False)
        self._pi_fan_fan_on: bool = False

        self._hardware_available = False
        self._last_error: Exception | None = None
        self._laser_left_device = None
        self._laser_right_device = None
        self._led_r_device = None
        self._led_g_device = None
        self._led_b_device = None
        self._fan_device = None

        self._laser_status = {"left": False, "right": False}
        self._led_status = {"r": 0, "g": 0, "b": 0}
        self._pi_fan_speed: float = float(pi_fan_cfg.get("default_value", 0))

    # ------------------------------------------------------------------
    # Connection / lifecycle
    # ------------------------------------------------------------------

    @property
    def simulation(self) -> bool:
        return self._simulation

    @property
    def hardware_available(self) -> bool:
        return self._hardware_available

    @property
    def last_error(self) -> Exception | None:
        """Last exception raised while attempting to connect, if any."""
        return self._last_error

    def connect(self) -> bool:
        self._last_error = None
        if self._simulation:
            self._hardware_available = True
            return True
        cfg_in = self._hardware_config
        lasers_cfg = cfg_in.get("lasers", _DEFAULT_HARDWARE_CONFIG["lasers"])
        led_cfg = cfg_in.get("led_rgb", _DEFAULT_HARDWARE_CONFIG["led_rgb"])
        fans_cfg = cfg_in.get("fans", _DEFAULT_HARDWARE_CONFIG["fans"])
        pi_fan_cfg = fans_cfg.get("pi_fan", _DEFAULT_HARDWARE_CONFIG["fans"]["pi_fan"])
        out_factory = self._output_device_factory
        pwm_factory = self._pwm_device_factory
        needs_pwm = "led_rgb" in cfg_in
        if out_factory is None or (needs_pwm and pwm_factory is None):
            try:
                from gpiozero import OutputDevice, PWMOutputDevice
            except Exception as exc:
                self._last_error = exc
                self._hardware_available = False
                return False
            out_factory = out_factory or OutputDevice
            if needs_pwm:
                pwm_factory = pwm_factory or PWMOutputDevice
        try:
            # Lasers first (output_factory calls 0, 1)
            if "lasers" in cfg_in and out_factory:
                left_cfg = lasers_cfg.get("left", {})
                right_cfg = lasers_cfg.get("right", {})
                self._laser_left_device = out_factory(
                    left_cfg.get("gpio", 17), left_cfg.get("active_high", True), False
                )
                self._laser_right_device = out_factory(
                    right_cfg.get("gpio", 27), right_cfg.get("active_high", True), False
                )
            # Fan (output_factory call 2)
            fan_gpio = pi_fan_cfg.get("gpio", 18)
            fan_ah = pi_fan_cfg.get("active_high", True)
            fan_default = bool(pi_fan_cfg.get("default_value", 0))
            self._fan_device = out_factory(fan_gpio, fan_ah, fan_default)
            if "led_rgb" in cfg_in and pwm_factory:
                r_cfg = led_cfg.get("red", {})
                g_cfg = led_cfg.get("green", {})
                b_cfg = led_cfg.get("blue", {})
                self._led_r_device = pwm_factory(r_cfg.get("gpio", 22), True, False)
                self._led_g_device = pwm_factory(g_cfg.get("gpio", 23), True, False)
                self._led_b_device = pwm_factory(b_cfg.get("gpio", 24), True, False)
            self._hardware_available = True
            return True
        except Exception as exc:
            self._last_error = exc
            self._hardware_available = False
            return False

    def close(self) -> None:
        for device_name in (
            "_laser_left_device",
            "_laser_right_device",
            "_led_r_device",
            "_led_g_device",
            "_led_b_device",
            "_fan_device",
        ):
            device = getattr(self, device_name)
            if device is None:
                continue
            try:
                device.close()
            except Exception:
                pass
            setattr(self, device_name, None)
        self._hardware_available = False
        self._pi_fan_speed = 0.0

    # ------------------------------------------------------------------
    # Laser
    # ------------------------------------------------------------------

    def laser_on(self, side: str) -> bool:
        if side not in ("left", "right"):
            return False
        if not self._hardware_available and not self._simulation:
            return False
        if side == "left":
            if self._laser_left_device is None and not self._simulation:
                return False
            if self._laser_left_device is not None:
                self._laser_left_device.on()
            self._laser_status["left"] = True
        else:
            if self._laser_right_device is None and not self._simulation:
                return False
            if self._laser_right_device is not None:
                self._laser_right_device.on()
            self._laser_status["right"] = True
        return True

    def laser_off(self, side: str) -> bool:
        if side not in ("left", "right"):
            return False
        if not self._hardware_available and not self._simulation:
            return False
        if side == "left":
            if self._laser_left_device is None and not self._simulation:
                return False
            if self._laser_left_device is not None:
                self._laser_left_device.off()
            self._laser_status["left"] = False
        else:
            if self._laser_right_device is None and not self._simulation:
                return False
            if self._laser_right_device is not None:
                self._laser_right_device.off()
            self._laser_status["right"] = False
        return True

    def get_laser_status(self) -> dict[str, bool]:
        return dict(self._laser_status)

    # ------------------------------------------------------------------
    # LED
    # ------------------------------------------------------------------

    def led_set(self, r: int, g: int, b: int) -> bool:
        if not self._hardware_available and not self._simulation:
            return False
        if (
            not self._simulation
            and (
                self._led_r_device is None
                or self._led_g_device is None
                or self._led_b_device is None
            )
        ):
            return False
        self._led_status = {"r": r, "g": g, "b": b}
        if self._led_r_device is not None:
            self._led_r_device.value = r / 255.0
        if self._led_g_device is not None:
            self._led_g_device.value = g / 255.0
        if self._led_b_device is not None:
            self._led_b_device.value = b / 255.0
        return True

    def get_led_status(self) -> dict[str, int]:
        return dict(self._led_status)

    def led_set_mode(self, mode: str) -> None:
        if mode not in _LED_MODES:
            raise ValueError(f"Unknown LED mode: {mode!r}. Valid modes: {sorted(_LED_MODES)}")

    # ------------------------------------------------------------------
    # Fan
    # ------------------------------------------------------------------

    def set_fan_speed(self, speed: float) -> bool:
        if not self._hardware_available and not self._simulation:
            return False
        speed = max(0.0, min(1.0, speed))
        new_speed = 1.0 if speed > 0 else 0.0
        self._pi_fan_speed = new_speed
        if self._fan_device is not None:
            if new_speed > 0:
                self._fan_device.on()
            else:
                self._fan_device.off()
        return True

    def get_fan_status(self) -> dict:
        return {"speed": self._pi_fan_speed}

    def update_pi_fan_auto_control(self) -> bool:
        reader = self._temperature_reader
        try:
            temp = reader() if reader is not None else 0.0
        except Exception:
            self._pi_fan_speed = 1.0
            return True
        if self._pi_fan_fan_on:
            if temp <= self._pi_fan_off_temp:
                self._pi_fan_fan_on = False
                self._pi_fan_speed = 0.0
        else:
            if temp >= self._pi_fan_on_temp:
                self._pi_fan_fan_on = True
                self._pi_fan_speed = 1.0
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "simulation": self._simulation,
            "hardware_available": self._hardware_available,
            "pins": {
                "laser_left": self._pin_laser_left,
                "laser_right": self._pin_laser_right,
                "led_r": self._pin_led_r,
                "led_g": self._pin_led_g,
                "led_b": self._pin_led_b,
                "fan_pi": self._pin_fan_pi,
            },
        }
>>>>>>> origin/main
