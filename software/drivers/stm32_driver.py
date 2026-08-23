"""
STM32 driver aligned with the repository's binary USB packet protocol.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional

from firmware.raspberry_pi.config import USB_DEVICE_PID, USB_DEVICE_VID
from firmware.raspberry_pi.usb_driver import (
    CMD_GET_STATUS,
    CMD_HOME_X,
    CMD_HOME_Y,
    CMD_HOME_Z,
    CMD_MOVE_X,
    CMD_MOVE_Y,
    CMD_MOVE_Z,
    CMD_STOP,
    PyUSBTransport,
    ScannerStatus,
    USBProtocolError,
    USBScannerDriver,
)
from software.api import config_manager

logger = logging.getLogger(__name__)

DEFAULT_STEPS_PER_ROTATION = 200
DEFAULT_MOTOR_LIMITS = {
    "X": {"max_velocity": 300.0, "homing_speed": 50.0, "position_min": 0.0, "position_max": 210.0},
    "Y": {"max_velocity": 300.0, "homing_speed": 90.0, "position_min": 0.0, "position_max": 628.32},
    "Z": {"max_velocity": 5.0, "homing_speed": 50.0, "position_min": 0.0, "position_max": 270.0},
}
AXIS_COMMANDS = {
    "X": {"move": CMD_MOVE_X, "home": CMD_HOME_X, "status_attr": "pos_x"},
    "Y": {"move": CMD_MOVE_Y, "home": CMD_HOME_Y, "status_attr": "pos_y"},
    "Z": {"move": CMD_MOVE_Z, "home": CMD_HOME_Z, "status_attr": "pos_z"},
}


class STM32Driver:
    """
    High-level STM32 driver backed by the repo's binary USB packet protocol.

    Positions are tracked from firmware status frames so the software state is
    resynchronised after each successful command and on reconnect.
    """

    def __init__(
        self,
        *,
        transport: Optional[Any] = None,
        vendor_id: int = USB_DEVICE_VID,
        product_id: int = USB_DEVICE_PID,
        out_ep: int = 0x01,
        in_ep: int = 0x81,
        timeout_ms: int = 250,
        hardware_config: Optional[dict] = None,
    ):
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.out_ep = out_ep
        self.in_ep = in_ep
        self.timeout_ms = timeout_ms
        self.protocol = "binary_usb"
        self.supports_temperature = False
        self.supports_fan_control = False
        self.connected = False
        self.last_error: Optional[str] = None

        self._hardware_config = hardware_config or config_manager.load_hardware_config()
        self._steps_per_rotation = DEFAULT_STEPS_PER_ROTATION
        self._motors = self._build_motor_config(self._hardware_config)
        self._transport = transport
        self._owns_transport = transport is None
        self._driver: Optional[USBScannerDriver] = None
        self._position: Dict[str, float] = {axis: cfg["position_min"] for axis, cfg in self._motors.items()}
        self._raw_steps: Dict[str, int] = {axis: 0 for axis in self._motors}
        self._homed: Dict[str, bool] = {axis: False for axis in self._motors}

    @staticmethod
    def _build_motor_config(hardware_config: dict) -> Dict[str, Dict[str, float]]:
        motors = hardware_config.get("motors", {})
        result: Dict[str, Dict[str, float]] = {}
        for axis, defaults in DEFAULT_MOTOR_LIMITS.items():
            source = motors.get(axis.lower(), {})
            result[axis] = {
                "microsteps": float(source.get("microsteps", 16)),
                "rotation_distance": float(source.get("rotation_distance", 1.0)),
                "max_velocity": float(source.get("max_velocity", defaults["max_velocity"])),
                "homing_speed": float(source.get("homing_speed", defaults["homing_speed"])),
                "position_min": float(source.get("position_min", defaults["position_min"])),
                "position_max": float(source.get("position_max", defaults["position_max"])),
            }
        return result

    @property
    def is_connected(self) -> bool:
        return self.connected and self._driver is not None

    def connect(self) -> bool:
        """Create the binary USB transport and sync initial firmware state."""
        try:
            transport = self._transport
            if transport is None:
                transport = PyUSBTransport(
                    vendor_id=self.vendor_id,
                    product_id=self.product_id,
                    out_ep=self.out_ep,
                    in_ep=self.in_ep,
                    timeout_ms=self.timeout_ms,
                )
            self._transport = transport
            self._driver = USBScannerDriver(transport)
            status = self._driver.get_status()
            self._sync_from_status(status)
            self.connected = True
            self.last_error = None
            logger.info(
                "STM32 connected via binary USB protocol (vid=0x%04x pid=0x%04x)",
                self.vendor_id,
                self.product_id,
            )
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.connected = False
            self._driver = None
            if self._owns_transport:
                self._transport = None
            logger.error("STM32 connect error: %s", exc)
            return False

    def disconnect(self) -> None:
        """Drop the current transport/driver state."""
        self.connected = False
        self._driver = None
        if self._owns_transport:
            self._transport = None
        logger.info("STM32 disconnected")

    def ensure_connected(self) -> None:
        """Ensure the firmware is reachable before handling a request."""
        if self.is_connected:
            return
        if not self.connect():
            raise ConnectionError(self.last_error or "STM32 unavailable")

    def _require_driver(self) -> USBScannerDriver:
        self.ensure_connected()
        assert self._driver is not None
        return self._driver

    def _steps_per_mm(self, axis: str) -> float:
        cfg = self._motors[axis]
        return (self._steps_per_rotation * cfg["microsteps"]) / cfg["rotation_distance"]

    def _mm_to_steps(self, axis: str, distance_mm: float) -> int:
        return int(round(distance_mm * self._steps_per_mm(axis)))

    def _steps_to_mm(self, axis: str, steps: int) -> float:
        return steps / self._steps_per_mm(axis)

    def _velocity_to_step_speed(self, axis: str, velocity_mm_s: float) -> int:
        return max(1, int(round(velocity_mm_s * self._steps_per_mm(axis))))

    def _sync_from_status(self, status: ScannerStatus) -> None:
        for axis, meta in AXIS_COMMANDS.items():
            steps = int(getattr(status, meta["status_attr"]))
            self._raw_steps[axis] = steps
            self._position[axis] = self._steps_to_mm(axis, steps)
            self._homed[axis] = bool(status.endstop_mask & (1 << ("XYZ".index(axis))))

    def refresh_status(self) -> ScannerStatus:
        """Fetch and cache the latest firmware status frame."""
        driver = self._require_driver()
        try:
            status = driver.get_status()
            self._sync_from_status(status)
            self.connected = True
            self.last_error = None
            return status
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            raise ConnectionError(self.last_error) from exc

    def _validate_axis(self, axis: str) -> str:
        axis = axis.upper()
        if axis not in self._motors:
            raise ValueError("axis must be X, Y, or Z")
        return axis

    def _validate_velocity(self, axis: str, velocity_mm_s: Optional[float]) -> float:
        cfg = self._motors[axis]
        velocity = cfg["max_velocity"] if velocity_mm_s is None else float(velocity_mm_s)
        if not math.isfinite(velocity) or velocity <= 0:
            raise ValueError("velocity must be a positive number")
        if velocity > cfg["max_velocity"]:
            raise ValueError(f"velocity must be <= {cfg['max_velocity']}")
        return velocity

    def motor_move(self, axis: str, distance_mm: float, velocity_mm_s: Optional[float] = None) -> Dict[str, Any]:
        """Move one axis and resynchronise state from the firmware response."""
        axis = self._validate_axis(axis)
        if not math.isfinite(distance_mm):
            raise ValueError("distance must be a finite number")
        velocity = self._validate_velocity(axis, velocity_mm_s)
        cfg = self._motors[axis]
        target_mm = self._position[axis] + distance_mm
        if not (cfg["position_min"] <= target_mm <= cfg["position_max"]):
            raise ValueError(
                f"{axis} target position {target_mm:.2f}mm is outside "
                f"[{cfg['position_min']:.2f}, {cfg['position_max']:.2f}]"
            )

        step_delta = self._mm_to_steps(axis, distance_mm)
        if step_delta == 0:
            return {"axis": axis, "distance_mm": distance_mm, "position_mm": self._position[axis], "steps": 0}

        speed = self._velocity_to_step_speed(axis, velocity)
        driver = self._require_driver()
        try:
            if axis == "X":
                status = driver.move_x(step_delta, speed=speed)
            elif axis == "Y":
                status = driver.move_y(step_delta, speed=speed)
            else:
                status = driver.move_z(step_delta, speed=speed)
            self._sync_from_status(status)
            self.connected = True
            self.last_error = None
            return {
                "axis": axis,
                "distance_mm": distance_mm,
                "position_mm": self._position[axis],
                "steps": step_delta,
                "speed_steps_s": speed,
            }
        except USBProtocolError as exc:
            self.connected = False
            self.last_error = str(exc)
            raise RuntimeError(self.last_error) from exc

    def motor_home(self, axis: str) -> Dict[str, Any]:
        """Home one axis and resynchronise state from the firmware response."""
        axis = self._validate_axis(axis)
        driver = self._require_driver()
        try:
            status = driver.home_axis(axis)
            self._sync_from_status(status)
            self.connected = True
            self.last_error = None
            return {"axis": axis, "position_mm": self._position[axis], "homed": self._homed[axis]}
        except USBProtocolError as exc:
            self.connected = False
            self.last_error = str(exc)
            raise RuntimeError(self.last_error) from exc

    def motor_home_all(self) -> Dict[str, Any]:
        """Home all axes sequentially."""
        results = {}
        for axis in ("X", "Y", "Z"):
            results[axis] = self.motor_home(axis)
        return results

    def motor_stop(self) -> Dict[str, Any]:
        """Emergency stop and refresh the cached positions."""
        driver = self._require_driver()
        try:
            status = driver.stop()
            self._sync_from_status(status)
            self.connected = True
            self.last_error = None
            return {"stopped": True, "endstop_mask": status.endstop_mask}
        except USBProtocolError as exc:
            self.connected = False
            self.last_error = str(exc)
            raise RuntimeError(self.last_error) from exc

    def motor_status(self) -> Dict[str, Any]:
        """Return the cached motor state and refresh it when connected."""
        if self.is_connected:
            try:
                self.refresh_status()
            except ConnectionError:
                pass
        return {
            "connected": self.is_connected,
            "protocol": self.protocol,
            "last_error": self.last_error,
            "axes": {
                axis: {
                    "position_mm": round(self._position[axis], 4),
                    "position_steps": self._raw_steps[axis],
                    "homed": self._homed[axis],
                    "position_min": self._motors[axis]["position_min"],
                    "position_max": self._motors[axis]["position_max"],
                    "max_velocity": self._motors[axis]["max_velocity"],
                }
                for axis in ("X", "Y", "Z")
            },
        }

    def hardware_status(self) -> Dict[str, Any]:
        """Expose transport readiness for the API status endpoint."""
        return {
            "connected": self.is_connected,
            "protocol": self.protocol,
            "last_error": self.last_error,
            "supports_temperature": self.supports_temperature,
            "supports_fan_control": self.supports_fan_control,
            "vendor_id": f"0x{self.vendor_id:04x}",
            "product_id": f"0x{self.product_id:04x}",
        }

    def read_temperature(self) -> Optional[float]:
        """Binary firmware does not expose temperature in this repository."""
        return None

    def fan_set(self, fan: str, speed: float) -> bool:
        """Binary firmware does not expose fan control in this repository."""
        logger.warning("Ignoring unsupported STM32 fan control request: fan=%s speed=%s", fan, speed)
        return False

    def get_status(self) -> Dict[str, Any]:
        """Return the latest raw firmware status in a JSON-friendly shape."""
        status = self.refresh_status()
        return {
            "command": CMD_GET_STATUS,
            "position_steps": {"X": status.pos_x, "Y": status.pos_y, "Z": status.pos_z},
            "endstop_mask": status.endstop_mask,
            "last_command_codes": {
                "move": {axis: AXIS_COMMANDS[axis]["move"] for axis in AXIS_COMMANDS},
                "home": {axis: AXIS_COMMANDS[axis]["home"] for axis in AXIS_COMMANDS},
                "stop": CMD_STOP,
            },
        }
