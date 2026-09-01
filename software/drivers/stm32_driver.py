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

    def connect(self) -> bool:
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
            except ImportError:  # pragma: no cover
                self._connected = False
                return False
        try:
            self._port = factory(port, baud, timeout=timeout, write_timeout=timeout)
            self._port.reset_input_buffer()
            self._connected = True
            return True
        except Exception:
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
