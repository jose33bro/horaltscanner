"""
GPIO driver for Raspberry Pi lasers, RGB LED, and the Pi fan.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional, Tuple

from software.api import config_manager

logger = logging.getLogger(__name__)

DEFAULT_PINS = {
    "laser_left": 27,
    "laser_right": 22,
    "led_r": 18,
    "led_g": 13,
    "led_b": 19,
    "fan_pi": 23,
}

try:
    from gpiozero import LED as _GpioLED, PWMOutputDevice as _PWM

    _GPIOZERO_AVAILABLE = True
except Exception:
    _GPIOZERO_AVAILABLE = False
    logger.warning("gpiozero not available – GPIO driver running in simulation mode")


class GPIODriver:
    """High-level GPIO driver with simulation fallback."""

    def __init__(self, simulation: bool = False, hardware_config: Optional[dict] = None):
        self._hardware_config = hardware_config or config_manager.load_hardware_config()
        self.pins = self._load_pins(self._hardware_config)
        self._sim = simulation or not _GPIOZERO_AVAILABLE
        self._hardware_available = False

        self._laser_left: Optional[object] = None
        self._laser_right: Optional[object] = None
        self._led_r: Optional[object] = None
        self._led_g: Optional[object] = None
        self._led_b: Optional[object] = None
        self._fan: Optional[object] = None

        self._laser_left_on = False
        self._laser_right_on = False
        self._rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._fan_speed = 0.0
        self._animation_thread: Optional[threading.Thread] = None
        self._animation_stop = threading.Event()

        if not self._sim:
            self._init_gpio()

    @staticmethod
    def _load_pins(hardware_config: dict) -> Dict[str, int]:
        lasers = hardware_config.get("lasers", {})
        led = hardware_config.get("led_rgb", {})
        fans = hardware_config.get("fans", {})
        return {
            "laser_left": int(lasers.get("left", {}).get("gpio", DEFAULT_PINS["laser_left"])),
            "laser_right": int(lasers.get("right", {}).get("gpio", DEFAULT_PINS["laser_right"])),
            "led_r": int(led.get("red", {}).get("gpio", DEFAULT_PINS["led_r"])),
            "led_g": int(led.get("green", {}).get("gpio", DEFAULT_PINS["led_g"])),
            "led_b": int(led.get("blue", {}).get("gpio", DEFAULT_PINS["led_b"])),
            "fan_pi": int(fans.get("pi_fan", {}).get("gpio", DEFAULT_PINS["fan_pi"])),
        }

    @property
    def simulation(self) -> bool:
        return self._sim

    @property
    def hardware_available(self) -> bool:
        return self._hardware_available

    def _init_gpio(self) -> None:
        """Initialise gpiozero device objects."""
        try:
            self._laser_left = _GpioLED(self.pins["laser_left"])
            self._laser_right = _GpioLED(self.pins["laser_right"])
            self._led_r = _PWM(self.pins["led_r"])
            self._led_g = _PWM(self.pins["led_g"])
            self._led_b = _PWM(self.pins["led_b"])
            self._fan = _PWM(self.pins["fan_pi"])
            self._hardware_available = True
            logger.info("GPIO driver initialised (hardware mode)")
        except Exception as exc:
            self._sim = True
            self._hardware_available = False
            logger.error("GPIO init error: %s – falling back to simulation", exc)

    def _stop_animation(self) -> None:
        self._animation_stop.set()
        thread = self._animation_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.2)
        self._animation_thread = None
        self._animation_stop.clear()

    def _start_animation(self, target) -> None:
        self._stop_animation()
        self._animation_thread = threading.Thread(target=target, daemon=True)
        self._animation_thread.start()

    def laser_left_on(self) -> None:
        self._laser_left_on = True
        if self._hardware_available and self._laser_left:
            self._laser_left.on()

    def laser_left_off(self) -> None:
        self._laser_left_on = False
        if self._hardware_available and self._laser_left:
            self._laser_left.off()

    def laser_right_on(self) -> None:
        self._laser_right_on = True
        if self._hardware_available and self._laser_right:
            self._laser_right.on()

    def laser_right_off(self) -> None:
        self._laser_right_on = False
        if self._hardware_available and self._laser_right:
            self._laser_right.off()

    def laser_status(self) -> dict:
        return {
            "left": self._laser_left_on,
            "right": self._laser_right_on,
            "simulation": self.simulation,
            "hardware_available": self.hardware_available,
        }

    def _apply_rgb(self, r: int, g: int, b: int) -> None:
        r_f = max(0.0, min(1.0, r / 255.0))
        g_f = max(0.0, min(1.0, g / 255.0))
        b_f = max(0.0, min(1.0, b / 255.0))
        self._rgb = (r_f, g_f, b_f)
        if self._hardware_available:
            if self._led_r:
                self._led_r.value = r_f
            if self._led_g:
                self._led_g.value = g_f
            if self._led_b:
                self._led_b.value = b_f

    def led_set_rgb(self, r: int, g: int, b: int) -> None:
        self._stop_animation()
        self._apply_rgb(r, g, b)

    def led_off(self) -> None:
        self.led_set_rgb(0, 0, 0)

    def led_set_mode(self, mode: str) -> None:
        mode = mode.lower()
        presets = {
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255),
            "white": (255, 255, 255),
            "off": (0, 0, 0),
        }
        if mode in presets:
            self.led_set_rgb(*presets[mode])
            return
        if mode == "pulse":
            self._start_animation(self._led_pulse_bg)
            return
        if mode == "rainbow":
            self._start_animation(self._led_rainbow_bg)
            return
        raise ValueError(f"unknown LED mode: {mode}")

    def _led_pulse_bg(self) -> None:
        for v in range(0, 256, 16):
            if self._animation_stop.is_set():
                return
            self._apply_rgb(0, 0, v)
            time.sleep(0.02)
        for v in range(255, -1, -16):
            if self._animation_stop.is_set():
                return
            self._apply_rgb(0, 0, v)
            time.sleep(0.02)
        self._apply_rgb(0, 0, 0)

    def _led_rainbow_bg(self) -> None:
        for hue in range(0, 360, 10):
            if self._animation_stop.is_set():
                return
            r, g, b = _hsv_to_rgb(hue / 360.0, 1.0, 1.0)
            self._apply_rgb(r, g, b)
            time.sleep(0.03)
        self._apply_rgb(0, 0, 0)

    def led_status(self) -> dict:
        r_f, g_f, b_f = self._rgb
        return {
            "r": round(r_f * 255),
            "g": round(g_f * 255),
            "b": round(b_f * 255),
            "simulation": self.simulation,
            "hardware_available": self.hardware_available,
        }

    def fan_on(self, speed: float = 1.0) -> None:
        speed = max(0.0, min(1.0, speed))
        self._fan_speed = speed
        if self._hardware_available and self._fan:
            self._fan.value = speed

    def fan_off(self) -> None:
        self._fan_speed = 0.0
        if self._hardware_available and self._fan:
            self._fan.value = 0.0

    def fan_status(self) -> dict:
        return {"speed": self._fan_speed, "on": self._fan_speed > 0}

    def status(self) -> dict:
        return {
            "simulation": self.simulation,
            "hardware_available": self.hardware_available,
            "pins": dict(self.pins),
            "lasers": self.laser_status(),
            "led": self.led_status(),
            "fan": self.fan_status(),
        }

    def shutdown(self) -> None:
        self._stop_animation()
        self.laser_left_off()
        self.laser_right_off()
        self.fan_off()
        self.led_off()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()


def _hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    import colorsys

    r_f, g_f, b_f = colorsys.hsv_to_rgb(h, s, v)
    return int(r_f * 255), int(g_f * 255), int(b_f * 255)
