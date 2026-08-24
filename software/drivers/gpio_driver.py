"""GPIO driver for HoralScanner lasers, LED, and fans.

Supports a *simulation* mode (no hardware required) used by the test suite.
"""
from __future__ import annotations


_DEFAULT_HARDWARE_CONFIG: dict = {
    "lasers": {"left": {"gpio": 17}, "right": {"gpio": 27}},
    "led_rgb": {"red": {"gpio": 22}, "green": {"gpio": 23}, "blue": {"gpio": 24}},
    "fans": {"pi_fan": {"gpio": 18}},
}

_LED_MODES = {"off", "on", "pulse"}


class GPIODriver:
    """Lightweight GPIO driver with an optional simulation mode."""

    def __init__(
        self,
        simulation: bool = False,
        hardware_config: dict | None = None,
    ) -> None:
        self._simulation = simulation
        cfg = hardware_config if hardware_config is not None else _DEFAULT_HARDWARE_CONFIG

        self._pin_laser_left: int = cfg.get("lasers", {}).get("left", {}).get("gpio", 17)
        self._pin_laser_right: int = cfg.get("lasers", {}).get("right", {}).get("gpio", 27)
        self._pin_led_r: int = cfg.get("led_rgb", {}).get("red", {}).get("gpio", 22)
        self._pin_led_g: int = cfg.get("led_rgb", {}).get("green", {}).get("gpio", 23)
        self._pin_led_b: int = cfg.get("led_rgb", {}).get("blue", {}).get("gpio", 24)
        self._pin_fan_pi: int = cfg.get("fans", {}).get("pi_fan", {}).get("gpio", 18)

        self._hardware_available = False
        if not simulation:
            try:
                import RPi.GPIO  # noqa: F401
                self._hardware_available = True
            except ImportError:
                pass

    # ------------------------------------------------------------------
    # LED helpers
    # ------------------------------------------------------------------

    def led_set_mode(self, mode: str) -> None:
        if mode not in _LED_MODES:
            raise ValueError(f"Unknown LED mode: {mode!r}. Valid modes: {sorted(_LED_MODES)}")

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
