<<<<<<< HEAD
"""
STM32 Driver - Serial communication with Creality V4.2.2 (STM32F103RET6).

Protocol: simple text commands over USB-CDC at 115200 baud.
Commands are newline-terminated; the firmware replies with a
single line starting with "OK" or "ERR".

Motor pin mapping (from printer.cfg):
  X: step=PC2, dir=PB9, enable=!PC3  rotation_distance=40mm
  Y: step=PB8, dir=!PB7, enable=!PC3 rotation_distance=620mm
  Z: step=PB6, dir=!PB5, enable=!PC3 rotation_distance=8mm

Temperature sensor: PC5 (EPCOS 100K B57560G104F)
Fan pins: PA0 (part fan), PA8 (temperature-controlled fan)
"""

import logging
import re
import time
from typing import Optional, Dict, Tuple
from enum import Enum

import serial

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Motor configuration mirrors printer.cfg
# ---------------------------------------------------------------------------

STEPS_PER_ROTATION = 200  # NEMA17 full-step

MOTORS: Dict[str, Dict] = {
    "X": {
        "microsteps": 16,
        "rotation_distance": 40,   # mm
        "max_velocity": 300,       # mm/s
        "max_accel": 3000,         # mm/s²
        "position_min": 0.0,
        "position_max": 210.0,     # mm
        "homing_speed": 50,        # mm/s
    },
    "Y": {
        "microsteps": 16,
        "rotation_distance": 620,  # mm (turntable circumference)
        "max_velocity": 300,
        "max_accel": 3000,
        "position_min": 0.0,
        "position_max": 628.32,    # mm (full rotation)
        "homing_speed": 90,
    },
    "Z": {
        "microsteps": 16,
        "rotation_distance": 8,    # mm
        "max_velocity": 5,
        "max_accel": 100,
        "position_min": 0.0,
        "position_max": 270.0,     # mm
        "homing_speed": 50,
    },
}


class CommandStatus(Enum):
    SUCCESS = "OK"
    ERROR = "ERR"
    UNKNOWN = "UNKNOWN"


class STM32Driver:
    """
    Low-level serial driver for the Creality V4.2.2 STM32F103.

    Sends text commands and parses single-line responses.
    All motor positions are tracked in software; the firmware only
    accepts step-count moves.
    """

    DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"

    def __init__(self, port: str = DEFAULT_PORT, baudrate: int = 115200,
                 timeout: float = 5.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None
        self.connected = False

        # Software position tracking
        self._position: Dict[str, float] = {ax: 0.0 for ax in MOTORS}
        self._homed: Dict[str, bool] = {ax: False for ax in MOTORS}

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Open the serial port and verify firmware responds."""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
            logger.info("STM32 port opened: %s @ %d baud", self.port, self.baudrate)
            self.connected = True
            if self.ping():
                logger.info("STM32 handshake OK")
                return True
            logger.warning("STM32 ping failed – firmware may not be running")
            self.connected = False
            return False
        except serial.SerialException as exc:
            logger.error("STM32 connect error: %s", exc)
            self.connected = False
            return False

    def disconnect(self) -> None:
        """Close the serial port."""
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.connected = False
        logger.info("STM32 disconnected")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    # ------------------------------------------------------------------
    # Raw command layer
    # ------------------------------------------------------------------

    def send_command(self, command: str) -> Optional[str]:
        """Send *command* and return the stripped response line, or None."""
        if not self.connected or not self.ser:
            logger.error("STM32 not connected")
            return None
        try:
            self.ser.write((command + "\n").encode("utf-8"))
            logger.debug("TX: %s", command)
            response = self._read_response()
            if response:
                logger.debug("RX: %s", response)
            return response
        except serial.SerialException as exc:
            logger.error("send_command error: %s", exc)
            self.connected = False
            return None

    def _read_response(self) -> Optional[str]:
        """Read one response line from the firmware."""
        try:
            line = self.ser.readline().decode("utf-8").strip()
            return line if line else None
        except (serial.SerialException, UnicodeDecodeError) as exc:
            logger.error("read_response error: %s", exc)
            return None

    def _parse_response(self, response: Optional[str]) -> Tuple[CommandStatus, str]:
        """Parse ``"OK <payload>"`` or ``"ERR <reason>"``."""
        if not response:
            return CommandStatus.UNKNOWN, ""
        parts = response.split(maxsplit=1)
        status_str = parts[0]
        payload = parts[1] if len(parts) > 1 else ""
        if status_str == "OK":
            return CommandStatus.SUCCESS, payload
        if status_str == "ERR":
            return CommandStatus.ERROR, payload
        return CommandStatus.UNKNOWN, response

    # ------------------------------------------------------------------
    # Firmware commands
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if the firmware responds with ``OK PONG``."""
        response = self.send_command("PING")
        status, payload = self._parse_response(response)
        return status == CommandStatus.SUCCESS and "PONG" in payload

    # ------------------------------------------------------------------
    # Motor control
    # ------------------------------------------------------------------

    def _mm_to_steps(self, axis: str, distance_mm: float) -> int:
        cfg = MOTORS[axis]
        steps_per_mm = (STEPS_PER_ROTATION * cfg["microsteps"]) / cfg["rotation_distance"]
        return int(distance_mm * steps_per_mm)

    def _steps_to_mm(self, axis: str, steps: int) -> float:
        cfg = MOTORS[axis]
        steps_per_mm = (STEPS_PER_ROTATION * cfg["microsteps"]) / cfg["rotation_distance"]
        return steps / steps_per_mm

    def _step_speed(self, axis: str, velocity_mm_s: float) -> int:
        cfg = MOTORS[axis]
        steps_per_mm = (STEPS_PER_ROTATION * cfg["microsteps"]) / cfg["rotation_distance"]
        return int(velocity_mm_s * steps_per_mm)

    def motor_move(self, axis: str, distance_mm: float,
                   velocity_mm_s: Optional[float] = None) -> bool:
        """
        Move *axis* by *distance_mm* (relative, mm).

        Checks software position limits; sends ``MOVE <axis> <steps> <speed>``.
        """
        axis = axis.upper()
        if axis not in MOTORS:
            logger.error("Invalid axis: %s", axis)
            return False

        cfg = MOTORS[axis]
        new_pos = self._position[axis] + distance_mm
        if not (cfg["position_min"] <= new_pos <= cfg["position_max"]):
            logger.error("%s: target position %.2fmm out of range [%.1f, %.1f]",
                         axis, new_pos, cfg["position_min"], cfg["position_max"])
            return False

        steps = self._mm_to_steps(axis, distance_mm)
        speed = self._step_speed(axis, velocity_mm_s or cfg["max_velocity"])
        response = self.send_command(f"MOVE {axis} {steps} {speed}")
        status, _ = self._parse_response(response)
        if status == CommandStatus.SUCCESS:
            self._position[axis] = new_pos
            return True
        logger.error("MOVE %s failed: %s", axis, response)
        return False

    def motor_home(self, axis: str) -> bool:
        """Home *axis* (sends ``HOME <axis>``)."""
        axis = axis.upper()
        if axis not in MOTORS:
            logger.error("Invalid axis: %s", axis)
            return False
        response = self.send_command(f"HOME {axis}")
        status, _ = self._parse_response(response)
        if status == CommandStatus.SUCCESS:
            self._position[axis] = MOTORS[axis]["position_min"]
            self._homed[axis] = True
            return True
        logger.error("HOME %s failed: %s", axis, response)
        return False

    def motor_home_all(self) -> bool:
        """Home all axes (X, Y, Z)."""
        return all(self.motor_home(ax) for ax in ("X", "Y", "Z"))

    def motor_stop(self) -> bool:
        """Emergency stop (sends ``STOP``)."""
        response = self.send_command("STOP")
        status, _ = self._parse_response(response)
        return status == CommandStatus.SUCCESS

    def motor_status(self) -> Dict:
        """Return software-tracked motor state."""
        return {
            axis: {
                "position_mm": self._position[axis],
                "homed": self._homed[axis],
                "position_min": MOTORS[axis]["position_min"],
                "position_max": MOTORS[axis]["position_max"],
            }
            for axis in MOTORS
        }

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

    def read_temperature(self) -> Optional[float]:
        """
        Read the board temperature from PC5 (sends ``TEMP``).

        Returns degrees Celsius, or None on error.
        """
        response = self.send_command("TEMP")
        status, payload = self._parse_response(response)
        if status == CommandStatus.SUCCESS:
            match = re.search(r"TEMP\s+([\d.]+)", payload)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass
            # Some firmware builds reply "OK 23.5" directly
            try:
                return float(payload.strip())
            except ValueError:
                pass
        logger.error("TEMP read failed: %s", response)
        return None
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
        except Exception as exc:
            self._last_error = exc
            self._port = None
            self._connected = False
            return False

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
    def fan_set(self, fan: str, speed: float) -> bool:
        """
        Set fan speed (0.0–1.0).

        *fan* is ``"part"`` (PA0) or ``"board"`` (PA8).
        Sends ``FAN <fan> <speed_percent>``.
        """
        fan = fan.lower()
        if fan not in ("part", "board"):
            logger.error("Invalid fan: %s", fan)
            return False
        pct = int(max(0.0, min(1.0, speed)) * 100)
        response = self.send_command(f"FAN {fan.upper()} {pct}")
        status, _ = self._parse_response(response)
        return status == CommandStatus.SUCCESS

    def fan_on(self, fan: str = "part", speed: float = 1.0) -> bool:
        """Turn fan on at *speed* (0.0–1.0)."""
        return self.fan_set(fan, speed)

    def fan_off(self, fan: str = "part") -> bool:
        """Turn fan off."""
        return self.fan_set(fan, 0.0)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Optional[Dict]:
        """
        Request full status from firmware (sends ``STATUS``).

        Returns a dict parsed from ``"X:0.00 Y:0.00 Z:0.00 HX:0 HY:0 HZ:0"``.
        """
        response = self.send_command("STATUS")
        status, payload = self._parse_response(response)
        if status == CommandStatus.SUCCESS:
            result = {}
            for part in payload.split():
                if ":" in part:
                    key, value = part.split(":", 1)
                    try:
                        result[key] = float(value) if "." in value else int(value)
                    except ValueError:
                        pass
            return result or None
        return None
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

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

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
