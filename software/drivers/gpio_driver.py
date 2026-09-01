"""GPIO driver for HoralScanner lasers, LED, and fans.

Supports a *simulation* mode (no hardware required) used by the test suite.
"""
from __future__ import annotations

from pathlib import Path
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
        cpu_temperature_reader: Callable[[], float | None] | None = None,
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
        self._cpu_temperature_reader = cpu_temperature_reader or self._read_cpu_temperature

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

    def connect(self) -> bool:
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
        except Exception:
            self._hardware_available = False
            return False

    @property
    def simulation(self) -> bool:
        return self._simulation

    @property
    def hardware_available(self) -> bool:
        return self._hardware_available

    def close(self) -> None:
        for attribute in (
            "_laser_left_device",
            "_laser_right_device",
            "_led_r_device",
            "_led_g_device",
            "_led_b_device",
            "_fan_device",
        ):
            device = getattr(self, attribute)
            if device is None:
                continue
            try:
                device.close()
            except Exception:
                pass
            setattr(self, attribute, None)
        self._hardware_available = False
        self._pi_fan_speed = 0.0

    # ------------------------------------------------------------------
    # Laser
    # ------------------------------------------------------------------

    def laser_on(self, side: str) -> bool:
        if side not in ("left", "right"):
            return False
        if side == "left":
            if self._laser_left_device is not None:
                self._laser_left_device.on()
            self._laser_status["left"] = True
        else:
            if self._laser_right_device is not None:
                self._laser_right_device.on()
            self._laser_status["right"] = True
        return True

    def laser_off(self, side: str) -> bool:
        if side not in ("left", "right"):
            return False
        if side == "left":
            if self._laser_left_device is not None:
                self._laser_left_device.off()
            self._laser_status["left"] = False
        else:
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

    @staticmethod
    def _read_cpu_temperature() -> float | None:
        """Read the Raspberry Pi SoC temperature exposed by the Linux kernel."""
        try:
            millidegrees = int(
                Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
            )
        except (OSError, ValueError):
            return None
        return millidegrees / 1000.0

    def read_cpu_temperature(self) -> float | None:
        try:
            return self._cpu_temperature_reader()
        except (OSError, ValueError):
            return None

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
