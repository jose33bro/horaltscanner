from __future__ import annotations

from dataclasses import dataclass

from .pi_hardware import LaserController, SensorRig
from .usb_driver import CrealityUsbDriver


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

    def acquire_scan_step(self, x_steps: int, sync_token: str) -> dict:
        self.move_x(x_steps)
        sync_response = self.usb.sync(sync_token)
        payload = self.sensors.capture_frame()
        payload["sync"] = sync_response
        return payload
