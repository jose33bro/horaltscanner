from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TypedDict, cast

from .pi_hardware import LaserController, SensorRig
from .usb_driver import CrealityUsbDriver


class ScanStepPayload(TypedDict):
    lidar_distance_mm: Optional[float]
    usb_camera_frame: Optional[bytes]
    csi_camera_frame: Optional[bytes]
    sync: str


@dataclass
class ScanController:
    usb: CrealityUsbDriver
    lasers: LaserController
    sensors: SensorRig

    def move_x(self, steps: int, speed: int = 400) -> str:
        return self.usb.move("X", steps, speed)

    def move_y(self, steps: int, speed: int = 300) -> str:
        return self.usb.move("Y", steps, speed)

    def move_z(self, steps: int, speed: int = 200) -> str:
        return self.usb.move("Z", steps, speed)

    def home_y_to_lidar_zero(self) -> str:
        return self.usb.home_y()

    def acquire_scan_step(self, x_steps: int, sync_token: str) -> ScanStepPayload:
        self.move_x(x_steps)
        self.lasers.set_state(True, True)
        try:
            sync_response = self.usb.sync(sync_token)
            payload = self.sensors.capture_frame()
        finally:
            self.lasers.set_state(False, False)
        payload["sync"] = sync_response
        return cast(ScanStepPayload, payload)
