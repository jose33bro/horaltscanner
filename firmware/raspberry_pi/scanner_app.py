from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .gpio_laser_control import LaserController
from .motor_control import MotorController, ScanPoint


class SensorArray(Protocol):
    def capture(self) -> dict[str, Any]:
        """Capture synchronized sensors (LiDAR + cameras)."""


@dataclass(frozen=True)
class CaptureFrame:
    point: ScanPoint
    sensors: dict[str, Any]


class ScannerApp:
    def __init__(self, controller: MotorController, lasers: LaserController, sensors: SensorArray):
        self._controller = controller
        self._lasers = lasers
        self._sensors = sensors

    def run_scan(self, x_offsets: list[int], z_offsets: list[int], rotation_steps: int, step_per_rotation: int) -> list[CaptureFrame]:
        frames: list[CaptureFrame] = []

        def _capture(point: ScanPoint) -> None:
            frames.append(CaptureFrame(point=point, sensors=self._sensors.capture()))

        self._lasers.enable_both()
        try:
            self._controller.perform_scan_sequence(
                x_offsets=x_offsets,
                z_offsets=z_offsets,
                rotation_steps=rotation_steps,
                step_per_rotation=step_per_rotation,
                on_capture=_capture,
            )
        finally:
            self._lasers.disable_both()

        return frames
