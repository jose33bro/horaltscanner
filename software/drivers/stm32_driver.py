"""STM32 driver for HoralScanner motor and fan control.

Supports simulation mode (no hardware required) for the test suite.
"""
from __future__ import annotations

import re
import threading
import time
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
        self._io_lock = threading.Lock()
        self._motion_lock = threading.Lock()
        self._stop_generation = 0
        self._connected = False
        self._last_error: Exception | None = None
        temperature_cfg = self._hardware_config.get("temperature", {})
        fan_cfg = temperature_cfg.get("board_fan_control", {})
        self._board_fan_auto = bool(fan_cfg.get("auto_control", True))
        self._board_fan_on_temp = float(fan_cfg.get("on_temp_c", fan_cfg.get("target_temp", 37) + 2))
        self._board_fan_off_temp = float(fan_cfg.get("off_temp_c", fan_cfg.get("target_temp", 37) - 2))
        if self._board_fan_on_temp <= self._board_fan_off_temp:
            raise ValueError("board fan on temperature must be greater than off temperature")
        self._board_fan_error: str | None = None
        self._board_fan_on = False

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
        with self._io_lock:
            self._port.write((cmd + "\n").encode())
            response = self._port.readline().decode("ascii", errors="replace").strip()
        return response.startswith("OK")

    def _send_and_read(self, cmd: str) -> str:
        """Send command and return raw response line."""
        if self._port is None:
            return ""
        with self._io_lock:
            self._port.write((cmd + "\n").encode())
            return self._port.readline().decode("ascii", errors="replace").strip()

    def _send_motion_command(self, cmd: str, generation: int) -> bool:
        """Order motion against STOP without making STOP wait on a whole move."""
        if self._simulation:
            if generation != self._stop_generation:
                return False
            return self._send_command(cmd)
        if self._port is None:
            return False
        with self._io_lock:
            if generation != self._stop_generation:
                return False
            self._port.write((cmd + "\n").encode())
            response = self._port.readline().decode("ascii", errors="replace").strip()
            return response.startswith("OK")

    def _wait_for_motion(self, timeout_s: float, poll_interval_s: float) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            response = self._send_and_read("MOTION_STATUS")
            if "DONE" in response:
                return "done"
            if "STOPPED" in response:
                return "stopped"
            if "ERROR" in response:
                return "error"
            time.sleep(poll_interval_s)
        return "timeout"

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

    def update_board_fan_auto_control(self) -> bool:
        """Apply hysteresis control to the PA8 fan from the PC5 thermistor."""
        if not self._board_fan_auto:
            return True
        temperature = self.read_board_temperature()
        if temperature is None:
            self._board_fan_error = "Temperature probe PC5 unavailable"
            # Fail safe: keep the board fan running if the probe is disconnected.
            self._board_fan_on = True
            return self.set_fan_speed("temperature", 1.0)

        self._board_fan_error = None
        if self._board_fan_on:
            if temperature <= self._board_fan_off_temp:
                self._board_fan_on = False
        elif temperature >= self._board_fan_on_temp:
            self._board_fan_on = True
        return self.set_fan_speed("temperature", 1.0 if self._board_fan_on else 0.0)

    def get_temperature_status(self) -> dict:
        """Return the read-only Creality probe and automatic fan state."""
        temperature = self.read_board_temperature()
        if temperature is None:
            self._board_fan_error = "Temperature probe PC5 unavailable"
        return {
            "sensor": "PC5",
            "sensor_type": "EPCOS 100K B57560G104F",
            "temperature_c": temperature,
            "connected": temperature is not None,
            "error": self._board_fan_error,
            "fan": "PA8",
            "fan_auto": self._board_fan_auto,
            "fan_on": self._board_fan_on,
            "on_temp_c": self._board_fan_on_temp,
            "off_temp_c": self._board_fan_off_temp,
        }

    # ------------------------------------------------------------------
    # Motor control
    # ------------------------------------------------------------------

    def _axis_cfg(self, axis: str) -> dict | None:
        return self._motor_cfg.get(axis.lower())

    def move_motor(self, axis: str, distance_mm: float) -> bool:
        generation = self._stop_generation
        with self._motion_lock:
            if generation != self._stop_generation:
                return False
            return self._move_motor_locked(axis, distance_mm, generation)

    def _move_motor_locked(
        self,
        axis: str,
        distance_mm: float,
        generation: int,
    ) -> bool:
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
        try:
            ok = self._send_motion_command(cmd, generation)
            if not ok:
                return False
            # In non-simulation mode wait for motion completion
            if not self._simulation and self._port is not None:
                self._motor_status["moving"][axis] = True
                serial_cfg = self._hardware_config.get("serial", {})
                timeout_s = float(serial_cfg.get("motion_timeout_s", 30.0))
                poll_interval_s = float(serial_cfg.get("motion_poll_interval_s", 0.02))
                try:
                    outcome = self._wait_for_motion(timeout_s, poll_interval_s)
                    if outcome != "done":
                        if outcome == "timeout":
                            self._send_command(f"STOP {axis.upper()}")
                        self._motor_status["homed"][axis] = False
                        return False
                finally:
                    self._motor_status["moving"][axis] = False
            if generation != self._stop_generation:
                self._motor_status["homed"][axis] = False
                return False
            self._motor_status["positions"][axis] = target
            return True
        except Exception:
            if not self._simulation:
                self._motor_status["homed"][axis] = False
            raise

    def home_motor(self, axis: str) -> bool:
        generation = self._stop_generation
        with self._motion_lock:
            if generation != self._stop_generation:
                return False
            return self._home_motor_locked(axis, generation)

    def _home_motor_locked(self, axis: str, generation: int) -> bool:
        axis = axis.lower()
        axes = ("x", "y", "z") if axis == "all" else (axis,)
        if any(self._axis_cfg(item) is None for item in axes):
            return False
        for item in axes:
            self._motor_status["homed"][item] = False

        command_target = "ALL" if axis == "all" else axis.upper()
        ok = self._send_motion_command(f"HOME {command_target}", generation)
        if not ok:
            return False
        if not self._simulation and self._port is not None:
            for item in axes:
                self._motor_status["moving"][item] = True
            serial_cfg = self._hardware_config.get("serial", {})
            timeout_s = float(serial_cfg.get("homing_timeout_s", 130.0))
            poll_interval_s = float(serial_cfg.get("motion_poll_interval_s", 0.02))
            try:
                outcome = self._wait_for_motion(timeout_s, poll_interval_s)
                if outcome != "done":
                    if outcome == "timeout":
                        self._send_command("STOP ALL")
                    return False
            finally:
                for item in axes:
                    self._motor_status["moving"][item] = False
        if generation != self._stop_generation:
            return False
        for item in axes:
            self._motor_status["positions"][item] = 0.0
            self._motor_status["homed"][item] = True
        return True

    def stop_motor(self, axis: str = "all") -> bool:
        self._stop_generation += 1
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
