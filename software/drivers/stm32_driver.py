"""
STM32Driver - High-level driver for the Creality V4.2.2 (STM32F103) board.

Wraps the text-based USB serial protocol exposed by the custom scanner firmware and
provides a clean interface for motors, fans and the board temperature sensor.

Fan GPIO mapping (from hardware/wiring_diagram.md):
  - PA0 → Creality mainboard fan (FAN_PA0_PWM <0-255>)
  - PA8 → Temperature-controlled fan (FAN_PA8_PWM <0-255>)
  - PC5 → NTC thermistor ADC input (GET_TEMP)

Temperature thresholds (from problem statement):
  - Fan ON:  > 50 °C
  - Fan OFF: < 45 °C
  - Alert:   > 55 °C
  - E-stop:  > 60 °C
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default USB serial path for Creality V4.2.2 on Raspberry Pi
_DEFAULT_USB_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"

# Fan temperature thresholds (°C)
FAN_ON_THRESHOLD = 50.0
FAN_OFF_THRESHOLD = 45.0
FAN_ALERT_THRESHOLD = 55.0
FAN_ESTOP_THRESHOLD = 60.0


class STM32Driver:
    """Driver for the Creality V4.2.2 board connected via USB serial."""

    def __init__(self, port: str = _DEFAULT_USB_PORT, baudrate: int = 115200, timeout: float = 5.0):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._connected = False
        self._serial = None

        # Software-tracked state
        self._axes: dict[str, dict] = {
            ax: {"position_mm": 0.0, "homed": False}
            for ax in ("X", "Y", "Z")
        }
        self._fan_speeds: dict[str, float] = {"creality": 0.0, "temperature": 0.0}

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Open USB serial connection.  Returns True on success."""
        try:
            import serial
            self._serial = serial.Serial(
                self._port, baudrate=self._baudrate, timeout=self._timeout
            )
            self._connected = True
            logger.info("STM32Driver connected on %s", self._port)
            return True
        except Exception as exc:
            logger.warning("STM32Driver connection failed: %s", exc)
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._connected = False

    def ensure_connected(self) -> None:
        """Raise ConnectionError if not connected."""
        if not self._connected:
            raise ConnectionError("STM32Driver is not connected")

    # ------------------------------------------------------------------
    # Low-level command transport
    # ------------------------------------------------------------------

    def _send_command(self, command: str) -> bool:
        """Send a text command over serial.  Returns True on success."""
        if self._serial is None:
            logger.debug("STM32Driver _send_command (no serial): %s", command)
            return False
        try:
            self._serial.write((command + "\n").encode("ascii"))
            response = self._serial.readline().decode("ascii", errors="replace").strip()
            if response.startswith("OK"):
                return True
            logger.warning("STM32 command rejected: %s → %s", command, response)
            return False
        except Exception as exc:
            logger.error("STM32 serial error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Motor control
    # ------------------------------------------------------------------

    def motor_move(self, axis: str, distance_mm: float, velocity: Optional[float] = None) -> dict:
        """Move *axis* by *distance_mm* mm.  Returns status dict."""
        axis = axis.upper()
        if axis not in self._axes:
            raise ValueError(f"Unknown axis: {axis}")

        # Build command string: MOVE_X/Y/Z <steps> <speed>
        steps_per_mm = self._steps_per_mm(axis)
        steps = int(round(distance_mm * steps_per_mm))
        speed = int(velocity * steps_per_mm) if velocity is not None else 0
        cmd = f"MOVE_{axis} {steps} {speed}"
        if not self._send_command(cmd):
            raise RuntimeError(f"Motor move failed for axis {axis}")

        self._axes[axis]["position_mm"] += distance_mm
        return {
            "axis": axis,
            "distance_mm": distance_mm,
            "position_mm": self._axes[axis]["position_mm"],
            "steps": steps,
            "speed_steps_s": speed,
        }

    def motor_home(self, axis: str) -> dict:
        """Home a single axis (or 'all')."""
        axis = axis.upper()
        if axis == "ALL":
            return self.motor_home_all()
        if axis not in self._axes:
            raise ValueError(f"Unknown axis: {axis}")
        if not self._send_command(f"HOME_{axis}"):
            raise RuntimeError(f"Homing failed for axis {axis}")
        self._axes[axis]["position_mm"] = 0.0
        self._axes[axis]["homed"] = True
        return {"axis": axis, "position_mm": 0.0, "homed": True}

    def motor_home_all(self) -> dict:
        """Home all three axes."""
        results = {}
        for ax in ("X", "Y", "Z"):
            results[ax] = self.motor_home(ax)
        return results

    def stop_motor(self, axis: str = "all") -> dict:
        """Emergency stop."""
        if not self._send_command("STOP"):
            raise RuntimeError("Motor stop command failed")
        return {"stopped": True, "endstop_mask": 0}

    def move_motor(self, axis: str, distance_mm: float, velocity: Optional[float] = None) -> dict:
        """Alias for motor_move()."""
        return self.motor_move(axis, distance_mm, velocity)

    def home_motor(self, axis: str) -> dict:
        """Alias for motor_home()."""
        return self.motor_home(axis)

    def motor_stop(self, axis: str = "all") -> dict:
        """Alias for stop_motor()."""
        return self.stop_motor(axis)

    def get_motor_status(self) -> dict:
        """Return software-tracked motor positions and homing state."""
        return {
            "connected": self._connected,
            "protocol": "serial_text",
            "last_error": None,
            "axes": {
                ax: dict(info)
                for ax, info in self._axes.items()
            },
        }

    def motor_status(self) -> dict:
        """Alias for get_motor_status()."""
        return self.get_motor_status()

    # ------------------------------------------------------------------
    # Fan control
    # ------------------------------------------------------------------

    def set_fan_speed(self, fan: str, speed: float) -> bool:
        """Set fan speed (0.0–1.0).  Clamps out-of-range values.

        fan: 'creality' → PA0, 'temperature' → PA8
        """
        clamped = max(0.0, min(1.0, speed))
        pwm_value = int(clamped * 255)

        if fan == "creality":
            ok = self._send_command(f"FAN_PA0_PWM {pwm_value}")
        elif fan == "temperature":
            ok = self._send_command(f"FAN_PA8_PWM {pwm_value}")
        else:
            logger.warning("Unknown fan: %s", fan)
            return False

        if ok:
            self._fan_speeds[fan] = clamped
        return ok

    def get_fan_status(self) -> dict:
        return dict(self._fan_speeds)

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

    def read_board_temperature(self) -> Optional[float]:
        """Read board temperature from the NTC thermistor on PC5 (ADC).

        Sends GET_TEMP over serial and parses the response.
        Returns None if the reading fails.
        """
        if self._serial is None:
            logger.debug("STM32Driver read_board_temperature (no serial)")
            return None
        try:
            self._serial.write(b"GET_TEMP\n")
            response = self._serial.readline().decode("ascii", errors="replace").strip()
            if not response.startswith("OK"):
                logger.warning("Unexpected temperature response: %s", response)
                return None
            # Expected format: "OK 42.5" or "OK TEMP=42.5"
            for token in response.split():
                try:
                    return float(token)
                except ValueError:
                    if token.startswith("TEMP="):
                        try:
                            return float(token.removeprefix("TEMP="))
                        except ValueError:
                            pass
            logger.warning("Unexpected temperature response: %s", response)
            return None
        except Exception as exc:
            logger.error("Temperature read error: %s", exc)
            return None

    def read_temperature(self) -> Optional[float]:
        """Alias for read_board_temperature()."""
        return self.read_board_temperature()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _steps_per_mm(axis: str) -> float:
        """Return steps/mm for the given axis based on printer.cfg values."""
        cfg = {
            "X": {"microsteps": 16, "rotation_distance": 40},
            "Y": {"microsteps": 16, "rotation_distance": 620},
            "Z": {"microsteps": 16, "rotation_distance": 8},
        }[axis]
        return (200 * cfg["microsteps"]) / cfg["rotation_distance"]
