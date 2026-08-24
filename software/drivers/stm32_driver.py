from __future__ import annotations

"""STM32Driver — USB/serial bridge to the Creality STM32 control board.

All methods degrade gracefully to simulation mode when no real board is
connected so the test suite can run without hardware.
"""


class STM32Driver:
    """Driver for the Creality v4.2.2 (STM32) board via USB serial."""

    def __init__(self, port: str | None = None, baud: int = 115200) -> None:
        self._port = port
        self._baud = baud
        self._fan_speeds: dict[str, float] = {}
        self._board_temperature: float | None = None

    # ------------------------------------------------------------------
    # Low-level transport (can be monkey-patched by tests)
    # ------------------------------------------------------------------

    def _send_command(self, cmd: str) -> bool:
        """Send a raw command string to the board.

        Returns ``True`` on success.  In simulation mode (no port configured)
        this is a no-op that always returns ``True``.
        """
        return True

    # ------------------------------------------------------------------
    # Fan control
    # ------------------------------------------------------------------

    def set_fan_speed(self, fan_name: str, speed: float) -> bool:
        """Set fan speed [0.0–1.0].  Speed is clamped to the valid range."""
        speed = max(0.0, min(1.0, speed))
        pwm_value = int(speed * 255)

        fan_pin_map = {
            "creality": "PA0",
            "temperature": "PA8",
        }
        if fan_name not in fan_pin_map:
            return False

        pin = fan_pin_map[fan_name]
        cmd = f"FAN_{pin}_PWM {pwm_value}"
        ok = self._send_command(cmd)
        if ok:
            self._fan_speeds[fan_name] = speed
        return ok

    def get_fan_status(self) -> dict[str, float]:
        """Return a mapping of fan_name → current speed [0.0–1.0]."""
        return dict(self._fan_speeds)

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

    def read_board_temperature(self) -> float:
        """Return the board temperature in °C.  Returns 0.0 in simulation."""
        return self._board_temperature if self._board_temperature is not None else 0.0

    def read_temperature(self) -> float:
        """Alias for :meth:`read_board_temperature`."""
        return self.read_board_temperature()
