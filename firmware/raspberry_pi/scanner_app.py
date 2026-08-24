from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

try:
    from .gpio_laser_control import GPIOLaserControl, LaserController
    from .motor_control import MotorController, ScanPoint
    from .usb_driver import USBDriver
except ImportError:  # pragma: no cover - compatibility for direct test imports
    from gpio_laser_control import GPIOLaserControl, LaserController
    from motor_control import MotorController, ScanPoint
    from usb_driver import USBDriver


class SensorArray(Protocol):
    def capture(self) -> dict[str, Any]:
        """Capture synchronized sensors (LiDAR + cameras)."""


@dataclass(frozen=True)
class CaptureFrame:
    point: ScanPoint
    sensors: dict[str, Any]


class ScannerApp:
    def __init__(
        self,
        controller: MotorController | None = None,
        lasers: LaserController | None = None,
        sensors: SensorArray | None = None,
        *,
        use_gpio: bool = True,
    ):
        # Newer scan-sequence mode used by the binary-protocol tests.
        self._controller = controller
        self._lasers = lasers
        self._sensors = sensors

        # Backward-compatible orchestration mode used by the older app tests.
        # Skip creating hardware objects when the newer controller path is used.
        if controller is None:
            self.usb = USBDriver()
            self.gpio = GPIOLaserControl(use_board=use_gpio)
            self.motors = MotorController(self.usb)
        else:
            self.usb = USBDriver()  # kept for shutdown/legacy test attributes
            self.gpio = GPIOLaserControl(use_board=False)
            self.motors = controller
        self.running = False
        self.scan_active = False

    def initialize(self) -> bool:
        if not self.usb.connect():
            self.running = False
            return False
        self.motors.home_all()
        self.running = True
        return True

    def move_to(self, *, x: float | None = None, y: float | None = None, z: float | None = None) -> bool:
        if not self.running:
            return False
        moves = (("X", x), ("Y", y), ("Z", z))
        result = True
        for axis, value in moves:
            if value is None:
                continue
            result = self.motors.move_abs(axis, value) and result
        return result

    def laser_test(self, duration_ms: int = 100) -> None:
        self.gpio.laser_pulse(duration_ms)

    def led_test(self) -> None:
        for color in ("red", "green", "blue", "white"):
            self.gpio.led_on(color)

    def fan_test(self, speed: float = 1.0) -> None:
        self.gpio.fan_on(speed)
        self.gpio.fan_off()

    def cancel_scan(self) -> None:
        self.scan_active = False

    def shutdown(self) -> None:
        self.running = False
        self.gpio.shutdown()
        if getattr(self.usb, "connected", False):
            self.usb.disconnect()

    def run_scan(self, x_offsets: list[int], z_offsets: list[int], rotation_steps: int, step_per_rotation: int) -> list[CaptureFrame]:
        if self._controller is None or self._lasers is None or self._sensors is None:
            raise RuntimeError("run_scan requires controller, lasers, and sensors")

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
