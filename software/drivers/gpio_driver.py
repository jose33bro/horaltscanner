"""GPIODriver – simulation-safe GPIO abstraction for the HoralScanner software layer."""
from __future__ import annotations

_DEFAULT_CONFIG = {
    "lasers": {"left": {"gpio": 27}, "right": {"gpio": 22}},
    "led_rgb": {"red": {"gpio": 18}, "green": {"gpio": 13}, "blue": {"gpio": 19}},
    "fans": {"pi_fan": {"gpio": 23}},
}

_LED_MODES = {"off", "on", "pulse"}


class GPIODriver:
    """Hardware-abstraction driver for GPIO peripherals.

    When *simulation=True* (default when hardware is unavailable) all write
    operations are no-ops; ``status()`` reports the pin configuration so that
    tests can assert the correct pins are used.
    """

    def __init__(self, simulation: bool = False, hardware_config: dict | None = None):
        self._simulation = simulation
        cfg = hardware_config or _DEFAULT_CONFIG
        self._pins = {
            "laser_left": cfg.get("lasers", {}).get("left", {}).get("gpio", 27),
            "laser_right": cfg.get("lasers", {}).get("right", {}).get("gpio", 22),
            "led_r": cfg.get("led_rgb", {}).get("red", {}).get("gpio", 18),
            "led_g": cfg.get("led_rgb", {}).get("green", {}).get("gpio", 13),
            "led_b": cfg.get("led_rgb", {}).get("blue", {}).get("gpio", 19),
            "fan_pi": cfg.get("fans", {}).get("pi_fan", {}).get("gpio", 23),
        }
        self._hardware_available = self._try_init_hardware()

    def _try_init_hardware(self) -> bool:
        if self._simulation:
            return False
        try:
            import RPi.GPIO  # noqa: F401
            return True
        except Exception:
            return False

    # --- lasers ---

    def laser_on(self, side: str = "both") -> None:
        pass

    def laser_off(self, side: str = "both") -> None:
        pass

    # --- LED ---

    def led_set_mode(self, mode: str) -> None:
        if mode not in _LED_MODES:
            raise ValueError(f"Unknown LED mode: {mode!r}. Valid modes: {sorted(_LED_MODES)}")

    def led_set_color(self, r: float, g: float, b: float) -> None:
        pass

    # --- fans ---

    def fan_on(self, speed: float = 1.0) -> None:
        pass

    def fan_off(self) -> None:
        pass

    # --- introspection ---

    def status(self) -> dict:
        return {
            "simulation": self._simulation,
            "hardware_available": self._hardware_available,
            "pins": dict(self._pins),
        }
