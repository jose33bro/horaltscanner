"""STM32Driver – USB communication driver for the Creality v4.2.2 / STM32 board."""
from __future__ import annotations

_FAN_PINS = {
    "creality": "PA0",
    "temperature": "PA8",
}


class STM32Driver:
    """Driver for the custom STM32 scanner firmware.

    Provides fan control and temperature reading.  When no real USB device is
    present the driver operates in simulation mode: ``_send_command`` can be
    replaced in tests to intercept commands.
    """

    def __init__(self) -> None:
        self._fan_speeds: dict[str, float] = {}

    def _send_command(self, cmd: str) -> bool:  # pragma: no cover – replaced in tests
        return True

    # --- fan ---

    def set_fan_speed(self, fan: str, speed: float) -> bool:
        if fan not in _FAN_PINS:
            raise ValueError(f"Unknown fan: {fan!r}")
        speed = max(0.0, min(1.0, speed))
        pwm_value = int(speed * 255)
        pin = _FAN_PINS[fan]
        cmd = f"FAN_{pin}_PWM {pwm_value}"
        result = self._send_command(cmd)
        if result:
            self._fan_speeds[fan] = speed
        return bool(result)

    def get_fan_status(self) -> dict[str, float]:
        return dict(self._fan_speeds)

    # --- temperature ---

    def read_board_temperature(self) -> float:
        return 0.0

    def read_temperature(self) -> float:
        return self.read_board_temperature()
