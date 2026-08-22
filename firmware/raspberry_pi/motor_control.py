from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .usb_driver import ScannerStatus, USBScannerDriver


@dataclass(frozen=True)
class ScanPoint:
    x_index: int
    y_index: int
    z_index: int
    status: ScannerStatus


class MotorController:
    def __init__(self, driver: USBScannerDriver):
        self._driver = driver

    def home_all(self) -> None:
        self._driver.home_x()
        self._driver.home_y()
        self._driver.home_z()

    def set_translation(self, delta_steps: int, speed: int = 0) -> ScannerStatus:
        return self._driver.move_x(delta_steps, speed=speed)

    def rotate_step(self, delta_steps: int, speed: int = 0) -> ScannerStatus:
        return self._driver.move_y(delta_steps, speed=speed)

    def set_height(self, delta_steps: int, speed: int = 0) -> ScannerStatus:
        return self._driver.move_z(delta_steps, speed=speed)

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
