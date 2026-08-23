from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

try:
    from .usb_driver import ScannerStatus, USBScannerDriver
except ImportError:  # pragma: no cover - compatibility for direct test imports
    from usb_driver import ScannerStatus, USBScannerDriver


@dataclass(frozen=True)
class ScanPoint:
    x_index: int
    y_index: int
    z_index: int
    status: ScannerStatus


class MotorController:
    def __init__(self, driver: USBScannerDriver):
        self._driver = driver
        self.state = {
            axis: {"position": 0.0, "homed": False}
            for axis in ("X", "Y", "Z")
        }

    def home_all(self) -> bool:
        return self.home("X") and self.home("Y") and self.home("Z")

    def home(self, axis: str) -> bool:
        axis = axis.upper()
        if axis not in self.state:
            return False
        if hasattr(self._driver, "home_axis"):
            result = self._driver.home_axis(axis)
        elif hasattr(self._driver, "home"):
            result = self._driver.home(axis)
        else:
            result = getattr(self._driver, f"home_{axis.lower()}")()
        if result is False:
            return False
        self.state[axis]["position"] = 0.0
        self.state[axis]["homed"] = True
        return True

    def set_translation(self, delta_steps: int, speed: int = 0) -> ScannerStatus:
        return self._driver.move_x(delta_steps, speed=speed)

    def rotate_step(self, delta_steps: int, speed: int = 0) -> ScannerStatus:
        return self._driver.move_y(delta_steps, speed=speed)

    def set_height(self, delta_steps: int, speed: int = 0) -> ScannerStatus:
        return self._driver.move_z(delta_steps, speed=speed)

    def _motor_cfg(self, axis: str) -> dict:
        axis = axis.upper()
        defaults = {
            "X": {"microsteps": 16, "rotation_distance": 40, "position_max": 210},
            "Y": {"microsteps": 16, "rotation_distance": 620, "position_max": 628.32},
            "Z": {"microsteps": 16, "rotation_distance": 8, "position_max": 270},
        }
        return defaults[axis]

    def _mm_to_steps(self, axis: str, distance_mm: float) -> int:
        cfg = self._motor_cfg(axis)
        steps_per_mm = (200 * cfg["microsteps"]) / cfg["rotation_distance"]
        return int(round(distance_mm * steps_per_mm))

    def _steps_to_mm(self, axis: str, steps: int) -> float:
        cfg = self._motor_cfg(axis)
        steps_per_mm = (200 * cfg["microsteps"]) / cfg["rotation_distance"]
        return steps / steps_per_mm

    def move_abs(self, axis: str, target_mm: float, speed: int = 0) -> bool:
        axis = axis.upper()
        if axis not in self.state:
            return False
        cfg = self._motor_cfg(axis)
        if not (0 <= target_mm <= cfg["position_max"]):
            return False
        delta = target_mm - self.state[axis]["position"]
        return self.move_rel(axis, delta, speed=speed)

    def move_rel(self, axis: str, delta_mm: float, speed: int = 0) -> bool:
        axis = axis.upper()
        if axis not in self.state:
            return False
        target = self.state[axis]["position"] + delta_mm
        cfg = self._motor_cfg(axis)
        if not (0 <= target <= cfg["position_max"]):
            return False
        steps = self._mm_to_steps(axis, delta_mm)
        return self.move_steps(axis, steps, speed=speed)

    def move_steps(self, axis: str, steps: int, speed: int = 0) -> bool:
        axis = axis.upper()
        if axis not in self.state:
            return False
        if hasattr(self._driver, "move"):
            ok = self._driver.move(axis, steps, speed)
        else:
            move_fn = getattr(self._driver, f"move_{axis.lower()}")
            move_fn(steps, speed=speed)
            ok = True
        if ok:
            self.state[axis]["position"] += self._steps_to_mm(axis, steps)
        return bool(ok)

    def is_homed(self, axis: str | None = None) -> bool:
        if axis is None:
            return all(info["homed"] for info in self.state.values())
        axis = axis.upper()
        return bool(self.state.get(axis, {}).get("homed"))

    def perform_scan_sequence(
        self,
        x_offsets: Iterable[int],
        z_offsets: Iterable[int],
        rotation_steps: int,
        step_per_rotation: int,
        on_capture: Callable[[ScanPoint], None],
    ) -> None:
        self.home_all()
        current_x = 0
        current_z = 0

        for x_idx, x_target in enumerate(x_offsets):
            x_delta = x_target - current_x
            x_status = self.set_translation(x_delta)
            current_x = x_target
            for z_idx, z_target in enumerate(z_offsets):
                z_delta = z_target - current_z
                z_status = self.set_height(z_delta)
                current_z = z_target
                for y_idx in range(rotation_steps):
                    y_status = self.rotate_step(step_per_rotation)
                    on_capture(
                        ScanPoint(
                            x_index=x_idx,
                            y_index=y_idx,
                            z_index=z_idx,
                            status=ScannerStatus(
                                status=y_status.status,
                                error=y_status.error,
                                pos_x=x_status.pos_x,
                                pos_y=y_status.pos_y,
                                pos_z=z_status.pos_z,
                                endstop_mask=y_status.endstop_mask,
                            ),
                        )
                    )
