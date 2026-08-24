"""STM32 driver for HoralScanner motor and fan control.

Supports simulation mode (no hardware required) for the test suite.
"""
from __future__ import annotations


_FAN_CHANNELS: dict[str, str] = {
    "creality": "PA0",
    "temperature": "PA8",
}


class STM32Driver:
    """Driver for the STM32 co-processor managing motors and fans."""

    def __init__(self, simulation: bool = True) -> None:
        self._simulation = simulation
        self._fan_status: dict[str, float] = {name: 0.0 for name in _FAN_CHANNELS}

    # ------------------------------------------------------------------
    # Internal helpers (can be monkey-patched in tests)
    # ------------------------------------------------------------------

    def _send_command(self, cmd: str) -> bool:  # pragma: no cover
        if self._simulation:
            return True
        return False

    # ------------------------------------------------------------------
    # Fan control
    # ------------------------------------------------------------------

    def set_fan_speed(self, channel: str, speed: float) -> bool:
        if channel not in _FAN_CHANNELS:
            raise ValueError(f"Unknown fan channel: {channel!r}")
        speed = max(0.0, min(1.0, speed))
        pwm_value = int(speed * 255)
        pin = _FAN_CHANNELS[channel]
        success = self._send_command(f"FAN_{pin}_PWM {pwm_value}")
        if success:
            self._fan_status[channel] = speed
        return success

    def get_fan_status(self) -> dict[str, float]:
        return dict(self._fan_status)

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

    def read_board_temperature(self) -> float:  # pragma: no cover
        return 0.0

    def read_temperature(self) -> float:
        return self.read_board_temperature()
