<<<<<<< HEAD
"""
STM32Driver - High-level driver for the Creality V4.2.2 (STM32F103) board.

Wraps the binary USB protocol exposed by the custom scanner firmware and
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

    def get_motor_status(self) -> dict:
        """Return software-tracked motor positions and homing state."""
        return {
            "connected": self._connected,
            "protocol": "binary_usb",
            "last_error": None,
            "axes": {
                ax: dict(info)
                for ax, info in self._axes.items()
            },
        }
=======
"""STM32 driver for HoralScanner motor and fan control.

Supports simulation mode (no hardware required) for the test suite.
"""
from __future__ import annotations

import re
from typing import Callable

_FAN_CHANNELS: dict[str, str] = {
    "creality": "PA0",
    "temperature": "PA8",
}

# Used when no hardware_config is provided at all.
_DEFAULT_MOTOR_CONFIG: dict[str, dict] = {
    "x": {"rotation_distance": 1, "microsteps": 16, "steps_per_rotation": 200,
          "position_min": 0, "position_max": 210, "default_speed_mm_s": 6.25},
    "y": {"rotation_distance": 1, "microsteps": 16, "steps_per_rotation": 200,
          "position_min": 0, "position_max": 628.32, "default_speed_mm_s": 6.25},
    "z": {"rotation_distance": 1, "microsteps": 16, "steps_per_rotation": 200,
          "position_min": 0, "position_max": 270, "default_speed_mm_s": 6.25},
}

# Per-key fallbacks applied when hardware_config IS provided.
_MOTOR_FORMULA_DEFAULTS: dict = {
    "microsteps": 16,
    "steps_per_rotation": 200,
    "default_speed_mm_s": 50,
    "position_min": 0,
    "position_max": float("inf"),
}


def _mm_to_steps(axis_cfg: dict, mm: float) -> int:
    spm = (axis_cfg["steps_per_rotation"] * axis_cfg["microsteps"]) / axis_cfg["rotation_distance"]
    return int(round(abs(mm) * spm))


def _mm_s_to_steps_s(axis_cfg: dict, mm_s: float) -> int:
    spm = (axis_cfg["steps_per_rotation"] * axis_cfg["microsteps"]) / axis_cfg["rotation_distance"]
    return int(round(mm_s * spm))


class STM32Driver:
    """Driver for the STM32 co-processor managing motors and fans."""

    def __init__(
        self,
        simulation: bool = True,
        hardware_config: dict | None = None,
        serial_factory: Callable | None = None,
    ) -> None:
        self._simulation = simulation
        self._hardware_config = hardware_config or {}
        self._serial_factory = serial_factory
        self._port = None  # serial port object once connected
        self._connected = False
        self._last_error: Exception | None = None

        # Fan status
        self._fan_status: dict[str, float] = {name: 0.0 for name in _FAN_CHANNELS}

        # Motor config: when hardware_config is None use _DEFAULT_MOTOR_CONFIG; otherwise
        # use formula defaults merged with any per-axis overrides from hardware_config.
        motors_override = (hardware_config or {}).get("motors", {})
        self._motor_cfg: dict[str, dict] = {}
        for axis in ("x", "y", "z"):
            if hardware_config is None:
                self._motor_cfg[axis] = dict(_DEFAULT_MOTOR_CONFIG[axis])
            else:
                base = dict(_MOTOR_FORMULA_DEFAULTS)
                base.update(motors_override.get(axis, {}))
                self._motor_cfg[axis] = base

        self._motor_status: dict = {
            "positions": {a: 0.0 for a in ("x", "y", "z")},
            "moving": {a: False for a in ("x", "y", "z")},
            "homed": {a: False for a in ("x", "y", "z")},
            "temperature_c": 0.0,
        }

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._simulation or self._connected

    @property
    def last_error(self) -> Exception | None:
        """Last exception raised while attempting to connect, if any."""
        return self._last_error

    def connect(self) -> bool:
        self._last_error = None
        if self._simulation:
            self._connected = True
            return True
        serial_cfg = self._hardware_config.get("serial", {})
        port = serial_cfg.get("mcu_port", "/dev/horalscanner_mcu")
        baud = serial_cfg.get("baud", 115200)
        timeout = serial_cfg.get("timeout_s", 1.0)
        factory = self._serial_factory
        if factory is None:
            try:
                import serial as _serial
                factory = _serial.Serial
            except ImportError as exc:  # pragma: no cover
                self._last_error = exc
                self._connected = False
                return False
        try:
            self._port = factory(port, baud, timeout=timeout, write_timeout=timeout)
            self._port.reset_input_buffer()
            self._connected = True
            return True
        except Exception:
            self._port = None
            return False

    @property
    def connected(self) -> bool:
        return self._simulation or self._port is not None

    # ------------------------------------------------------------------
    # Internal helpers (can be monkey-patched in tests)
    # ------------------------------------------------------------------

    def _send_command(self, cmd: str) -> bool:
        if self._simulation:
            return True
        if self._port is None:
            return False
        self._port.write((cmd + "\n").encode())
        response = self._port.readline().decode("ascii", errors="replace").strip()
        return response.startswith("OK")

    def _send_and_read(self, cmd: str) -> str:
        """Send command and return raw response line."""
        if self._port is None:
            return ""
        self._port.write((cmd + "\n").encode())
        return self._port.readline().decode("ascii", errors="replace").strip()
>>>>>>> origin/main

    # ------------------------------------------------------------------
    # Fan control
    # ------------------------------------------------------------------

<<<<<<< HEAD
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
=======
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
>>>>>>> origin/main

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

<<<<<<< HEAD
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
            # Expected format: "OK 42.5" or "OK TEMP=42.5"
            for token in response.split():
                try:
                    return float(token)
                except ValueError:
                    continue
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
=======
    def read_board_temperature(self) -> float | None:
        if self._simulation:
            return self._motor_status["temperature_c"]
        resp = self._send_and_read("TEMP_PC5_READ")
        m = re.search(r"TEMP_PC5\s+([\d.]+)", resp)
        if m:
            try:
                val = float(m.group(1))
                self._motor_status["temperature_c"] = val
                return val
            except ValueError:
                return None
        return None

    def read_temperature(self) -> float | None:
        return self.read_board_temperature()

    # ------------------------------------------------------------------
    # Motor control
    # ------------------------------------------------------------------

    def _axis_cfg(self, axis: str) -> dict | None:
        return self._motor_cfg.get(axis.lower())

    def move_motor(self, axis: str, distance_mm: float) -> bool:
        axis = axis.lower()
        cfg = self._axis_cfg(axis)
        if cfg is None:
            return False
        if not self._motor_status["homed"].get(axis, False):
            return False
        current = self._motor_status["positions"][axis]
        target = current + distance_mm
        pos_min = cfg.get("position_min", 0)
        pos_max = cfg.get("position_max", float("inf"))
        if not (pos_min <= target <= pos_max):
            return False
        steps = _mm_to_steps(cfg, distance_mm)
        speed_steps = _mm_s_to_steps_s(cfg, cfg.get("default_speed_mm_s", 20))
        direction = 1 if distance_mm >= 0 else -1
        cmd = f"MOVE {axis.upper()} {steps * direction} {speed_steps}"
        ok = self._send_command(cmd)
        if not ok:
            return False
        # In non-simulation mode wait for motion completion
        if not self._simulation and self._port is not None:
            while True:
                resp = self._send_and_read("MOTION_STATUS")
                if "DONE" in resp:
                    break
                if "STOPPED" in resp:
                    self._motor_status["homed"][axis] = False
                    return False
        self._motor_status["positions"][axis] = target
        return True

    def home_motor(self, axis: str) -> bool:
        axis = axis.lower()
        if axis == "all":
            ok = all(self.home_motor(a) for a in ("x", "y", "z"))
            return ok
        cfg = self._axis_cfg(axis)
        if cfg is None:
            return False
        ok = self._send_command(f"HOME {axis.upper()}")
        if ok:
            self._motor_status["positions"][axis] = 0.0
            self._motor_status["homed"][axis] = True
        return ok

    def stop_motor(self, axis: str = "all") -> bool:
        axis = axis.lower()
        if axis == "all":
            ok = self._send_command("STOP ALL")
            if ok:
                for a in ("x", "y", "z"):
                    if self._motor_status["moving"].get(a):
                        self._motor_status["homed"][a] = False
                        self._motor_status["moving"][a] = False
            return ok
        cfg = self._axis_cfg(axis)
        if cfg is None:
            return False
        ok = self._send_command(f"STOP {axis.upper()}")
        if ok and self._motor_status["moving"].get(axis):
            self._motor_status["homed"][axis] = False
            self._motor_status["moving"][axis] = False
        return ok

    def get_motor_status(self) -> dict:
        return {
            "positions": dict(self._motor_status["positions"]),
            "moving": dict(self._motor_status["moving"]),
            "homed": dict(self._motor_status["homed"]),
            "temperature_c": self._motor_status["temperature_c"],
        }
>>>>>>> origin/main
