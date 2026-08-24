from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from .gpio_laser_control import LaserController
from .motor_control import MotorController, ScanPoint
from .fan_gpio_control import FanGPIOController, OverheatError


class SensorArray(Protocol):
    def capture(self) -> dict[str, Any]:
        """Capture synchronized sensors (LiDAR + cameras)."""


class TemperatureSource(Protocol):
    def get_temperature(self) -> float:
        """Return the current MCU temperature in °C."""


@dataclass(frozen=True)
class CaptureFrame:
    point: ScanPoint
    sensors: dict[str, Any]


class ScannerApp:
    """Orchestrates a 3-D scan sequence with optional thermal monitoring.

    If *temp_source* and *fan_controller* are provided the app will:
      - Verify temperature is below the warning threshold before starting.
      - Update the fan controller after every capture during the scan.
      - Pause automatically if the MCU temperature exceeds the emergency limit.
    """

    TEMP_PRE_SCAN_MAX = 55.0   # °C – refuse to start scan above this temperature
    TEMP_PAUSE_THRESHOLD = 60.0  # °C – pause/abort scan if temperature reaches this

    def __init__(
        self,
        controller: MotorController,
        lasers: LaserController,
        sensors: SensorArray,
        temp_source: Optional[TemperatureSource] = None,
        fan_controller: Optional[FanGPIOController] = None,
    ):
        self._controller = controller
        self._lasers = lasers
        self._sensors = sensors
        self._temp_source = temp_source
        self._fan_controller = fan_controller

    def _check_temperature(self) -> None:
        """Read current temperature and update fan; raise if scan is unsafe."""
        if self._temp_source is None:
            return
        temp = self._temp_source.get_temperature()
        if self._fan_controller is not None:
            try:
                self._fan_controller.update(temp)
            except OverheatError as exc:
                raise ScanAbortedError(str(exc)) from exc
        if temp >= self.TEMP_PRE_SCAN_MAX:
            raise ScanAbortedError(
                f"Temperature {temp:.1f} °C exceeds pre-scan limit "
                f"{self.TEMP_PRE_SCAN_MAX:.1f} °C"
            )

    def run_scan(self, x_offsets: list[int], z_offsets: list[int], rotation_steps: int, step_per_rotation: int) -> list[CaptureFrame]:
        self._check_temperature()

        frames: list[CaptureFrame] = []

        def _capture(point: ScanPoint) -> None:
            if self._temp_source is not None and self._fan_controller is not None:
                temp = self._temp_source.get_temperature()
                try:
                    self._fan_controller.update(temp)
                except OverheatError as exc:
                    raise ScanAbortedError(str(exc)) from exc
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


class ScanAbortedError(RuntimeError):
    """Raised when a scan is aborted due to thermal overload."""
