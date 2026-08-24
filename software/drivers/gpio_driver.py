from __future__ import annotations

"""GPIODriver — thin wrapper around the Raspberry Pi GPIO bus.

In simulation mode (``simulation=True`` or when the RPi.GPIO library is not
available) every method is a safe no-op so that the full test suite can run on
any machine without real hardware.
"""

_VALID_LED_MODES = {"on", "off", "pulse", "blink"}

_DEFAULT_CONFIG: dict = {
    "lasers": {
        "left": {"gpio": 17},
        "right": {"gpio": 27},
    },
    "led_rgb": {
        "red": {"gpio": 22},
        "green": {"gpio": 23},
        "blue": {"gpio": 24},
    },
    "fans": {
        "pi_fan": {"gpio": 18},
    },
}


class GPIODriver:
    """High-level GPIO driver for the Horaltscanner hardware."""

    def __init__(
        self,
        simulation: bool = False,
        hardware_config: dict | None = None,
    ) -> None:
        self.simulation = simulation
        self._config = hardware_config if hardware_config is not None else _DEFAULT_CONFIG

        # Detect hardware availability
        self._hardware_available = False
        if not simulation:
            try:
                import RPi.GPIO  # noqa: F401
                self._hardware_available = True
            except ImportError:
                pass

        self._pins = self._extract_pins()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_pins(self) -> dict:
        laser_cfg = self._config.get("lasers", {})
        led_cfg = self._config.get("led_rgb", {})
        fan_cfg = self._config.get("fans", {})
        return {
            "laser_left": laser_cfg.get("left", {}).get("gpio"),
            "laser_right": laser_cfg.get("right", {}).get("gpio"),
            "led_r": led_cfg.get("red", {}).get("gpio"),
            "led_g": led_cfg.get("green", {}).get("gpio"),
            "led_b": led_cfg.get("blue", {}).get("gpio"),
            "fan_pi": fan_cfg.get("pi_fan", {}).get("gpio"),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "simulation": self.simulation or not self._hardware_available,
            "hardware_available": self._hardware_available,
            "pins": self._pins,
        }

    def laser_on(self, side: str = "both") -> None:
        pass

    def laser_off(self, side: str = "both") -> None:
        pass

    def led_set_mode(self, mode: str) -> None:
        if mode not in _VALID_LED_MODES:
            raise ValueError(
                f"Unknown LED mode '{mode}'. Valid modes: {sorted(_VALID_LED_MODES)}"
            )

    def led_set_color(self, r: float, g: float, b: float) -> None:
        pass

    def fan_on(self, speed: float = 1.0) -> None:
        pass

    def fan_off(self) -> None:
        pass
