"""
Scanner Engine - 3D reconstruction (point cloud → mesh → STL/AMF)
Uses Open3D when available; falls back to a stub otherwise.
"""

import copy
import io
import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, List, Mapping, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    _CV2_AVAILABLE = False

try:
    import open3d as o3d
    _O3D_AVAILABLE = True
except ImportError:
    _O3D_AVAILABLE = False
    logger.warning("Open3D not available; reconstruction will return stubs")


# ---------------------------------------------------------------------------
# Point Cloud Store (accumulated during a scan)
# ---------------------------------------------------------------------------

#: Maximum number of points retained in memory. Once the buffer is full,
#: the oldest points are silently dropped (FIFO) so long-running scans on
#: memory-constrained devices (e.g. Raspberry Pi 4, 4GB RAM) never grow
#: without bound. ~200k points keeps the point cloud well under ~500MB.
MAX_POINTS = 200_000


@dataclass
class ScanData:
    max_points: int = MAX_POINTS
    points: Deque[List[float]] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))
    colors: Deque[List[float]] = field(default_factory=lambda: deque(maxlen=MAX_POINTS))

    def __post_init__(self) -> None:
        if self.points.maxlen != self.max_points:
            self.points = deque(self.points, maxlen=self.max_points)
        if self.colors.maxlen != self.max_points:
            self.colors = deque(self.colors, maxlen=self.max_points)

    def add_point(self, x: float, y: float, z: float,
                  r: float = 0.5, g: float = 0.5, b: float = 0.5) -> None:
        # deque with maxlen automatically discards the oldest entry once
        # full, bounding memory usage during long scans.
        self.points.append([x, y, z])
        self.colors.append([r, g, b])

    def point_count(self) -> int:
        return len(self.points)

    def clear(self) -> None:
        self.points.clear()
        self.colors.clear()

    def as_dict(self) -> dict:
        return {
            "points": list(self.points),
            "colors": list(self.colors),
            "count": len(self.points),
        }


# ---------------------------------------------------------------------------
# Scan Session
# ---------------------------------------------------------------------------

class ScanPreflightError(RuntimeError):
    """Raised when a real scan cannot safely start."""

    def __init__(self, blockers: list[str]):
        self.blockers = blockers
        super().__init__("Real scan preflight failed: " + "; ".join(blockers))


class ScanCancelled(RuntimeError):
    """Internal signal used to unwind an acquisition safely."""


class ScanSession:
    """Manage explicit synthetic or calibrated physical scan acquisition."""

    _REQUIRED_CAMERAS = ("pi", "usb")
    _LASER_SIDES = ("left", "right")
    _MAX_ROTATION_STEPS = 72
    _MAX_Z_LEVELS = 20
    _MAX_AXIS_TRAVEL_MM = 100.0

    def __init__(
        self,
        simulation: bool = False,
        *,
        motor_driver: Any = None,
        gpio_driver: Any = None,
        cameras: Mapping[str, Any] | None = None,
        lidar_driver: Any = None,
        config: Mapping[str, Any] | None = None,
        calibration: Mapping[str, Any] | None = None,
        saved_poses_provider: Callable[[], Mapping[str, Mapping[str, float]]] | None = None,
        laser_line_analyzer: Callable[[bytes], Mapping[str, Any]] | None = None,
        hardware_reservation: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._data = ScanData()
        self._lock = threading.RLock()
        self._scanning = False
        self._starting = False
        self._thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._operation_threads: set[threading.Thread] = set()
        self._start_time: float = 0.0
        self._end_time: float = 0.0
        self._quality: float = 0.0
        self._simulation = bool(simulation)
        self._motor = motor_driver
        self._gpio = gpio_driver
        self._cameras = dict(cameras or {})
        self._lidar = lidar_driver
        self._config = dict(config or {})
        self._calibration = dict(calibration or {})
        self._saved_poses_provider = saved_poses_provider or (lambda: {})
        self._laser_line_analyzer = laser_line_analyzer
        self._hardware_reservation = hardware_reservation
        self._hardware_reserved = False
        self._reservation_release_thread: threading.Thread | None = None
        self._sleep = sleep
        self._phase = "idle"
        self._progress = 0.0
        self._laser_side: str | None = None
        self._samples = 0
        self._camera_frames = 0
        self._lidar_samples = 0
        self._laser_detections = {side: 0 for side in self._LASER_SIDES}
        self._error: str | None = None
        self._last_blockers: list[str] = []
        self._axis_position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._motor_preparation: dict[str, float | bool] | None = None
        self._motion_fault: str | None = None

    def configure_hardware(
        self,
        *,
        motor_driver: Any,
        gpio_driver: Any,
        cameras: Mapping[str, Any],
        lidar_driver: Any,
    ) -> None:
        """Refresh shared runtime driver references without changing scan mode."""
        with self._lock:
            if self._scanning or self._starting:
                return
            self._motor = motor_driver
            self._gpio = gpio_driver
            self._cameras = dict(cameras)
            self._lidar = lidar_driver

    def update_calibration(self, calibration: Mapping[str, Any]) -> None:
        """Install a newly validated calibration when acquisition is idle."""
        with self._lock:
            if self._scanning or self._starting:
                raise RuntimeError("Cannot replace calibration during acquisition")
            self._calibration = copy.deepcopy(dict(calibration))

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------

    def readiness(
        self,
        *,
        probe: bool = False,
        _allow_starting: bool = False,
        _require_centered_x: bool = False,
        _probe_reserved: bool = False,
    ) -> dict:
        """Return actionable blockers; ``probe`` may initialize sensors."""
        if self._simulation:
            return {"ready": True, "mode": "simulation", "blockers": []}
        if (
            probe
            and not _allow_starting
            and not _probe_reserved
            and self._hardware_reservation is not None
            and not bool(
                getattr(
                    self._hardware_reservation,
                    "owned_by_current_thread",
                    False,
                )
            )
        ):
            if not self._hardware_reservation.acquire(blocking=False):
                return {
                    "ready": False,
                    "mode": "real",
                    "blockers": ["Scanner hardware is busy with another operation"],
                }
            with self._lock:
                self._hardware_reserved = True
            try:
                return self.readiness(probe=True, _probe_reserved=True)
            finally:
                self._release_hardware_reservation()

        blockers: list[str] = []
        with self._lock:
            active = self._scanning or (self._starting and not _allow_starting)
            self._operation_threads = {
                thread for thread in self._operation_threads if thread.is_alive()
            }
            outstanding_operations = len(self._operation_threads)
        if probe and active:
            return {
                "ready": False,
                "mode": "real",
                "blockers": ["Cannot probe hardware while a scan is active"],
            }
        if outstanding_operations:
            blockers.append(
                f"{outstanding_operations} timed-out hardware operation(s) are still running"
            )
        if self._motion_fault:
            blockers.append(self._motion_fault)
        if self._motor is None or not bool(getattr(self._motor, "connected", False)):
            blockers.append("Creality STM32 motor controller is not connected")

        gpio_simulation = bool(getattr(self._gpio, "simulation", False))
        gpio_available = bool(getattr(self._gpio, "hardware_available", False))
        if self._gpio is None or gpio_simulation or not gpio_available:
            blockers.append("Physical GPIO laser driver is not connected")
        elif probe:
            try:
                self._lasers_off()
            except RuntimeError as exc:
                blockers.append(str(exc))

        motor_status: dict = {}
        if self._motor is not None:
            try:
                motor_status = self._motor.get_motor_status()
                self._axis_position = {
                    axis: float(motor_status.get("positions", {}).get(axis, 0.0))
                    for axis in ("x", "y", "z")
                }
            except Exception as exc:
                blockers.append(f"Motor status unavailable: {exc}")

        for axis in self._required_axes():
            auto_x = axis == "x" and self._automatic_x_center_enabled()
            if (
                not bool(motor_status.get("homed", {}).get(axis, False))
                and (not auto_x or _require_centered_x)
            ):
                blockers.append(f"Axis {axis.upper()} must be homed before a physical scan")
            if bool(motor_status.get("moving", {}).get(axis, False)):
                blockers.append(f"Axis {axis.upper()} is still moving; wait or stop it before scanning")

        blockers.extend(self._validate_calibration())

        pose_name = str(self._config.get("scan_pose_camera", "pi"))
        try:
            poses = self._saved_poses_provider() or {}
        except Exception as exc:
            poses = {}
            blockers.append(f"Saved scan poses could not be loaded: {exc}")
        pose = poses.get(pose_name)
        if not isinstance(pose, Mapping) or not all(axis in pose for axis in ("x", "y", "z")):
            blockers.append(
                f"Saved scan pose '{pose_name}' is missing; save it with POST /api/scan/pose/save"
            )
            pose = None
        blockers.extend(self._validate_trajectory(motor_status, pose))

        for name in self._REQUIRED_CAMERAS:
            camera = self._cameras.get(name)
            if camera is None:
                blockers.append(f"Camera '{name}' driver is unavailable")
                continue
            opened = bool(getattr(camera, "is_open", False))
            if probe and not opened:
                try:
                    if not camera.open():
                        blockers.append(
                            f"Camera '{name}' failed to open: "
                            f"{getattr(camera, 'last_error', 'unknown error')}"
                        )
                    else:
                        opened = True
                except Exception as exc:
                    blockers.append(f"Camera '{name}' failed to open: {exc}")
            elif not probe and not bool(getattr(camera, "is_open", False)):
                blockers.append(f"Camera '{name}' has not passed an open/capture check")
            if probe and opened:
                try:
                    frame = self._invoke_with_timeout(
                        camera.capture_jpeg,
                        self._positive_float("capture_timeout_s", 5.0),
                        f"Camera '{name}' preflight capture",
                    )
                    if not frame:
                        blockers.append(
                            f"Camera '{name}' opened but capture failed: "
                            f"{getattr(camera, 'last_error', 'unknown error')}"
                        )
                except Exception as exc:
                    blockers.append(f"Camera '{name}' preflight capture failed: {exc}")

        if self._lidar is None:
            blockers.append("TF-Luna driver is unavailable")
        elif probe:
            try:
                if not bool(getattr(self._lidar, "connected", False)) and not self._lidar.connect():
                    blockers.append("TF-Luna failed to connect")
                else:
                    lidar_distance = self._read_lidar_sample()
                    if lidar_distance is None:
                        blockers.append("TF-Luna connected but returned no valid distance")
                    elif not self._lidar_distance_valid(float(lidar_distance)):
                        limits = self._lidar_limits()
                        blockers.append(
                            f"TF-Luna distance {float(lidar_distance):.1f} mm is outside "
                            f"calibrated range [{limits[0]:.1f}, {limits[1]:.1f}]"
                        )
            except Exception as exc:
                blockers.append(f"TF-Luna preflight failed: {exc}")
        elif not bool(getattr(self._lidar, "connected", False)):
            blockers.append("TF-Luna is not connected")

        blockers = list(dict.fromkeys(blockers))
        with self._lock:
            self._last_blockers = blockers
        return {"ready": not blockers, "mode": "real", "blockers": blockers}

    def probe_readiness_with_reservation(self) -> dict:
        """Adopt a request reservation and quarantine timed-out probe workers."""
        owns_reservation = bool(
            self._hardware_reservation is not None
            and getattr(
                self._hardware_reservation,
                "owned_by_current_thread",
                False,
            )
        )
        if not owns_reservation:
            return self.readiness(probe=True)
        with self._lock:
            self._hardware_reserved = True
        try:
            return self.readiness(probe=True, _probe_reserved=True)
        finally:
            self._release_hardware_reservation()

    def _required_axes(self) -> tuple[str, ...]:
        # The saved scan pose contains all three axes, so every axis must have a
        # trustworthy reference even when only Y/Z move during acquisition.
        return ("x", "y", "z")

    def _validate_trajectory(
        self,
        motor_status: Mapping[str, Any],
        saved_pose: Mapping[str, Any] | None,
    ) -> list[str]:
        blockers: list[str] = []
        effective_pose = saved_pose
        if saved_pose is not None and self._automatic_x_center_enabled():
            try:
                effective_pose = dict(saved_pose)
                effective_pose["x"] = self._x_center_details()["target_mm"]
            except RuntimeError as exc:
                blockers.append(str(exc))
        try:
            rotation_axis = str(self._config.get("rotation_axis", "y")).lower()
            z_axis = str(self._config.get("z_axis", "z")).lower()
            if rotation_axis not in {"x", "y", "z"}:
                blockers.append(f"rotation_axis '{rotation_axis}' is invalid")
            if z_axis not in {"x", "y", "z"}:
                blockers.append(f"z_axis '{z_axis}' is invalid")
            if rotation_axis == z_axis:
                blockers.append("rotation_axis and z_axis must be different")
            rotation_steps = self._positive_int("rotation_steps", 3)
            z_levels = self._positive_int("z_levels", 2)
            rotation_step = self._positive_float("rotation_step_mm", 5.0)
            z_step = self._positive_float("z_step_mm", 5.0)
            configured_cap = min(
                self._positive_float("max_axis_travel_mm", self._MAX_AXIS_TRAVEL_MM),
                self._MAX_AXIS_TRAVEL_MM,
            )
        except (TypeError, ValueError) as exc:
            return [f"Invalid scan trajectory configuration: {exc}"]

        if rotation_steps > self._MAX_ROTATION_STEPS:
            blockers.append(f"rotation_steps exceeds safety cap {self._MAX_ROTATION_STEPS}")
        if z_levels > self._MAX_Z_LEVELS:
            blockers.append(f"z_levels exceeds safety cap {self._MAX_Z_LEVELS}")
        rotation_travel = rotation_step * max(0, rotation_steps - 1)
        z_travel = z_step * max(0, z_levels - 1)
        if rotation_travel > configured_cap or z_travel > configured_cap:
            blockers.append(
                f"Trajectory travel exceeds configured {configured_cap:.1f} mm safety cap"
            )

        positions = motor_status.get("positions", {}) if motor_status else {}
        limits = self._config.get("axis_limits_mm", {})
        for axis in ("x", "y", "z"):
            axis_limits = limits.get(axis, {}) if isinstance(limits, Mapping) else {}
            if not isinstance(axis_limits, Mapping) or "min" not in axis_limits or "max" not in axis_limits:
                blockers.append(f"Explicit scan axis_limits_mm.{axis} are required")
                continue
            try:
                low = float(axis_limits["min"])
                high = float(axis_limits["max"])
                current = float(positions.get(axis, 0.0))
                start = float(effective_pose[axis]) if effective_pose is not None else current
            except (KeyError, TypeError, ValueError) as exc:
                blockers.append(f"Axis {axis.upper()} limits or saved pose are invalid: {exc}")
                continue
            if not all(math.isfinite(value) for value in (low, high, current, start)) or high <= low:
                blockers.append(f"Axis {axis.upper()} limits and positions must be finite with max > min")
                continue
            axis_homed = bool(motor_status.get("homed", {}).get(axis, False))
            if axis_homed and not low <= current <= high:
                blockers.append(
                    f"Axis {axis.upper()} current position {current:.2f} mm is outside "
                    f"validated limits [{low:.2f}, {high:.2f}]"
                )
            travel = rotation_travel if axis == rotation_axis else z_travel if axis == z_axis else 0.0
            end = start + travel
            if not low <= start <= high or not low <= end <= high:
                blockers.append(
                    f"Axis {axis.upper()} scan path [{start:.2f}, {end:.2f}] is outside "
                    f"validated limits [{low:.2f}, {high:.2f}]"
                )
        return blockers

    def _automatic_x_center_enabled(self) -> bool:
        return bool(self._config.get("center_x_before_scan", True))

    def _x_center_details(self) -> dict[str, float]:
        limits = self._config.get("axis_limits_mm", {})
        scan_limits = limits.get("x") if isinstance(limits, Mapping) else None
        if not isinstance(scan_limits, Mapping):
            raise RuntimeError("Explicit scan axis_limits_mm.x are required for automatic centering")
        try:
            scan_low = float(scan_limits["min"])
            scan_high = float(scan_limits["max"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Axis X scan limits are invalid for automatic centering") from exc

        motor_limits_getter = getattr(self._motor, "get_motor_limits", None)
        raw_motor_limits = (
            motor_limits_getter("x")
            if callable(motor_limits_getter)
            else (scan_low, scan_high)
        )
        try:
            motor_low, motor_high = (float(value) for value in raw_motor_limits)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Axis X motor limits are invalid for automatic centering") from exc
        if not all(
            math.isfinite(value)
            for value in (scan_low, scan_high, motor_low, motor_high)
        ) or scan_high <= scan_low or motor_high <= motor_low:
            raise RuntimeError(
                "Axis X limits must be finite with max > min for automatic centering"
            )

        target = motor_low + (motor_high - motor_low) / 2.0
        if not scan_low <= target <= scan_high:
            raise RuntimeError(
                f"Axis X motor center {target:.2f} mm is outside validated scan limits "
                f"[{scan_low:.2f}, {scan_high:.2f}]"
            )
        return {
            "position_min_mm": motor_low,
            "position_max_mm": motor_high,
            "target_mm": target,
        }

    def _validate_calibration(self) -> list[str]:
        blockers: list[str] = []
        if not _CV2_AVAILABLE:
            blockers.append("OpenCV is required for physical laser-line extraction")
        board = self._calibration.get("checkerboard", {})
        try:
            board_valid = (
                board.get("board_columns") == 11
                and board.get("board_rows") == 6
                and math.isclose(
                    float(board.get("square_size_mm")),
                    13.0,
                    rel_tol=0,
                    abs_tol=1e-9,
                )
            )
        except (AttributeError, TypeError, ValueError):
            board_valid = False
        if not board_valid:
            blockers.append(
                "Calibration checkerboard metadata must be 11x6 inner corners with 13mm squares"
            )
        cameras = self._calibration.get("cameras", {})
        for name in self._REQUIRED_CAMERAS:
            camera = cameras.get(name, {}) if isinstance(cameras, Mapping) else {}
            intrinsic = camera.get("intrinsic_matrix")
            if not self._matrix_valid(intrinsic, (3, 3), invertible=True):
                blockers.append(f"Camera '{name}' intrinsic_matrix calibration is missing")
            distortion = camera.get("distortion_coefficients")
            try:
                distortion_values = np.asarray(distortion, dtype=float).reshape(-1)
                distortion_valid = (
                    len(distortion_values) >= 4
                    and bool(np.isfinite(distortion_values).all())
                )
            except (TypeError, ValueError):
                distortion_valid = False
            if not distortion_valid:
                blockers.append(f"Camera '{name}' distortion calibration is missing")
            if not self._matrix_valid(camera.get("camera_to_scanner"), (4, 4), transform=True):
                blockers.append(f"Camera '{name}' camera_to_scanner calibration is missing")
            quality = camera.get("quality", {})
            if (
                not isinstance(quality, Mapping)
                or not quality.get("accepted")
                or not self._finite_number(quality.get("rms_px"))
                or not self._finite_number(quality.get("maximum_rms_px"), positive=True)
                or float(quality["rms_px"]) > float(quality["maximum_rms_px"])
                or not self._finite_number(quality.get("extrinsic_translation_rms_mm"))
                or not self._finite_number(
                    quality.get("maximum_extrinsic_rms_mm"), positive=True
                )
                or float(quality["extrinsic_translation_rms_mm"])
                > float(quality["maximum_extrinsic_rms_mm"])
                or not self._finite_number(quality.get("extrinsic_rotation_rms_deg"))
                or not self._finite_number(
                    quality.get("maximum_extrinsic_rms_deg"), positive=True
                )
                or float(quality["extrinsic_rotation_rms_deg"])
                > float(quality["maximum_extrinsic_rms_deg"])
            ):
                blockers.append(f"Camera '{name}' calibration quality is missing or rejected")
            if camera.get("carriage_axis") and not self._vector_valid(
                camera.get("carriage_direction"),
                nonzero=True,
            ):
                blockers.append(f"Camera '{name}' carriage_direction calibration is invalid")
            if camera.get("carriage_axis") not in (None, "x", "y", "z"):
                blockers.append(f"Camera '{name}' carriage_axis calibration is invalid")
            self._validate_carriage_reference(
                f"Camera '{name}'", camera, blockers
            )
        planes = self._calibration.get("laser_planes", {})
        for side in self._LASER_SIDES:
            plane = planes.get(side, {}) if isinstance(planes, Mapping) else {}
            normal = plane.get("normal")
            if not self._vector_valid(normal, nonzero=True):
                blockers.append(f"Laser '{side}' calibrated plane normal is missing")
            if not self._finite_number(plane.get("offset_mm")):
                blockers.append(f"Laser '{side}' calibrated plane offset_mm is missing")
            quality = plane.get("quality", {})
            if (
                not isinstance(quality, Mapping)
                or not quality.get("accepted")
                or not self._finite_number(quality.get("rms_mm"))
                or not self._finite_number(quality.get("maximum_rms_mm"), positive=True)
                or float(quality["rms_mm"]) > float(quality["maximum_rms_mm"])
            ):
                blockers.append(f"Laser '{side}' calibration quality is missing or rejected")
        turntable = self._calibration.get("turntable", {})
        if not self._vector_valid(turntable.get("center_mm")):
            blockers.append("Turntable center_mm calibration is missing")
        if not self._vector_valid(turntable.get("axis"), nonzero=True):
            blockers.append("Turntable axis calibration is missing")
        if not self._finite_number(turntable.get("mm_per_revolution"), positive=True):
            blockers.append("Turntable mm_per_revolution calibration is missing")
        diameter = turntable.get("diameter_mm")
        circumference = turntable.get("mm_per_revolution")
        if (
            turntable.get("source") != "measured_diameter"
            or not isinstance(turntable.get("quality"), Mapping)
            or not turntable.get("quality", {}).get("accepted")
            or not self._finite_number(diameter, positive=True)
            or not self._finite_number(circumference, positive=True)
            or not math.isclose(
                float(circumference),
                math.pi * float(diameter),
                rel_tol=1e-8,
                abs_tol=1e-6,
            )
        ):
            blockers.append("Turntable circumference source/quality is missing")
        lidar = self._calibration.get("lidar", {})
        if not self._matrix_valid(lidar.get("lidar_to_scanner"), (4, 4), transform=True):
            blockers.append("TF-Luna lidar_to_scanner calibration is missing")
        if lidar.get("carriage_axis") and not self._vector_valid(
            lidar.get("carriage_direction"),
            nonzero=True,
        ):
            blockers.append("TF-Luna carriage_direction calibration is invalid")
        if lidar.get("carriage_axis") not in (None, "x", "y", "z"):
            blockers.append("TF-Luna carriage_axis calibration is invalid")
        self._validate_carriage_reference("TF-Luna", lidar, blockers)
        lidar_quality = lidar.get("quality", {})
        if (
            lidar.get("source") != "operator_measured_origin_direction"
            or not isinstance(lidar_quality, Mapping)
            or not lidar_quality.get("accepted")
            or not self._finite_number(lidar_quality.get("rms_mm"))
            or not self._finite_number(lidar_quality.get("maximum_rms_mm"), positive=True)
            or float(lidar_quality["rms_mm"])
            > float(lidar_quality["maximum_rms_mm"])
        ):
            blockers.append("TF-Luna transform source/quality is missing")
        try:
            low, high = self._lidar_limits()
            if not all(math.isfinite(value) for value in (low, high)) or low < 0 or high <= low:
                blockers.append("TF-Luna calibrated distance range must satisfy 0 <= min < max")
        except (TypeError, ValueError):
            blockers.append("TF-Luna calibrated distance range is invalid")
        x_scale = self._calibration.get("x_scale_validation", {})
        if (
            not isinstance(x_scale, Mapping)
            or not x_scale.get("accepted")
            or not self._finite_number(x_scale.get("measured_mm_per_commanded_mm"), positive=True)
            or not self._finite_number(x_scale.get("repeatability_rms_mm"))
            or not self._finite_number(
                x_scale.get("maximum_repeatability_mm"), positive=True
            )
            or float(x_scale["repeatability_rms_mm"])
            > float(x_scale["maximum_repeatability_mm"])
            or x_scale.get("motor_rotation_distance_changed") is not False
        ):
            blockers.append("X scale validation is missing or rejected")
        return blockers

    def _validate_carriage_reference(
        self,
        sensor_name: str,
        sensor_config: Mapping[str, Any],
        blockers: list[str],
    ) -> None:
        axis = sensor_config.get("carriage_axis")
        if axis not in {"x", "y", "z"}:
            return
        reference = sensor_config.get("reference_axis_position_mm")
        if not self._finite_number(reference):
            blockers.append(
                f"{sensor_name} reference_axis_position_mm is required for moving axis {axis.upper()}"
            )
            return
        limits = self._config.get("axis_limits_mm", {})
        axis_limits = limits.get(axis) if isinstance(limits, Mapping) else None
        try:
            low = float(axis_limits["min"])
            high = float(axis_limits["max"])
        except (KeyError, TypeError, ValueError):
            blockers.append(
                f"{sensor_name} reference cannot be validated because axis {axis.upper()} limits are invalid"
            )
            return
        reference_value = float(reference)
        if (
            not math.isfinite(low)
            or not math.isfinite(high)
            or high <= low
            or not low <= reference_value <= high
        ):
            blockers.append(
                f"{sensor_name} reference_axis_position_mm {reference_value:g} is outside "
                f"axis {axis.upper()} limits [{low:g}, {high:g}]"
            )

    @staticmethod
    def _finite_number(value: Any, *, positive: bool = False) -> bool:
        if isinstance(value, bool):
            return False
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and (number > 0 if positive else True)

    @staticmethod
    def _vector_valid(value: Any, *, nonzero: bool = False) -> bool:
        try:
            vector = np.asarray(value, dtype=float)
        except (TypeError, ValueError):
            return False
        return (
            vector.shape == (3,)
            and bool(np.isfinite(vector).all())
            and (not nonzero or float(np.linalg.norm(vector)) > 1e-9)
        )

    @staticmethod
    def _matrix_valid(
        value: Any,
        shape: tuple[int, int],
        *,
        invertible: bool = False,
        transform: bool = False,
    ) -> bool:
        try:
            matrix = np.asarray(value, dtype=float)
            if matrix.shape != shape or not bool(np.isfinite(matrix).all()):
                return False
            if invertible and abs(float(np.linalg.det(matrix))) <= 1e-12:
                return False
            if transform and (
                shape != (4, 4)
                or not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-6)
                or abs(float(np.linalg.det(matrix[:3, :3]))) <= 1e-12
            ):
                return False
            return True
        except (TypeError, ValueError, np.linalg.LinAlgError):
            return False

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._scanning or self._starting:
                raise RuntimeError("A scan is already running")
            if (
                not self._simulation
                and self._hardware_reservation is not None
                and not self._hardware_reservation.acquire(blocking=False)
            ):
                raise RuntimeError("Scanner hardware is busy with another operation")
            self._hardware_reserved = (
                not self._simulation and self._hardware_reservation is not None
            )
            self._starting = True
            self._cancel_event = threading.Event()
            self._phase = "preflight"
            self._motor_preparation = None
        try:
            readiness = self.readiness(
                probe=not self._simulation,
                _allow_starting=True,
            )
            if not readiness["ready"]:
                raise ScanPreflightError(readiness["blockers"])
            self._check_cancelled()
            if not self._simulation and self._automatic_x_center_enabled():
                try:
                    self._prepare_automatic_x_center()
                except Exception as exc:
                    raise ScanPreflightError(
                        [f"Automatic X homing/centering failed: {exc}"]
                    ) from exc
                readiness = self.readiness(
                    probe=False,
                    _allow_starting=True,
                    _require_centered_x=True,
                )
                if not readiness["ready"]:
                    raise ScanPreflightError(readiness["blockers"])
                self._check_cancelled()

            with self._lock:
                self._data.clear()
                self._scanning = True
                self._start_time = time.time()
                self._end_time = 0.0
                self._quality = 0.0
                self._phase = "starting"
                self._progress = 0.0
                self._laser_side = None
                self._samples = 0
                self._camera_frames = 0
                self._lidar_samples = 0
                self._laser_detections = {side: 0 for side in self._LASER_SIDES}
                self._error = None
                target = (
                    self._simulation_capture_loop
                    if self._simulation
                    else self._physical_capture_loop
                )
                thread = threading.Thread(
                    target=target,
                    name="scan-acquisition",
                    daemon=True,
                )
                self._thread = thread
                try:
                    thread.start()
                except Exception:
                    self._thread = None
                    self._scanning = False
                    self._phase = "error"
                    raise
        finally:
            with self._lock:
                self._starting = False
                release_reservation = not self._scanning and self._hardware_reserved
            if release_reservation:
                self._release_hardware_reservation()
        logger.info("Scan started in explicit mode=%s", self.mode)

    def stop(self) -> None:
        with self._lock:
            running = self._scanning or self._starting
            self._cancel_event.set()
            if running:
                self._phase = "cancelling"
        if running and not self._simulation:
            self._emergency_cleanup()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=self._positive_float("stop_join_timeout_s", 3.0))
        with self._lock:
            thread_alive = bool(thread and thread.is_alive())
            if self._scanning and not thread_alive:
                self._scanning = False
                self._phase = "cancelled"
                self._end_time = time.time()
            elif thread_alive:
                self._phase = "cleanup-timeout"
                self._error = "Acquisition cancellation is still completing; restart is blocked"
            if self._thread is thread and not thread_alive:
                self._thread = None
        logger.info("Scan stopped - %d points captured", self._data.point_count())

    @property
    def mode(self) -> str:
        return "simulation" if self._simulation else "real"

    @property
    def hardware_reserved(self) -> bool:
        with self._lock:
            return self._hardware_reserved

    def _simulation_capture_loop(self) -> None:
        angle = 0.0
        try:
            with self._lock:
                self._phase = "synthetic-generation"
            while not self._cancel_event.is_set():
                radius = 50.0
                x = radius * np.cos(np.radians(angle))
                z_val = radius * np.sin(np.radians(angle))
                for height in np.linspace(-30, 30, 5):
                    with self._lock:
                        self._data.add_point(
                            x + np.random.uniform(-1, 1),
                            float(height) + np.random.uniform(-0.5, 0.5),
                            z_val + np.random.uniform(-1, 1),
                            r=0.6, g=0.8, b=0.9,
                        )
                angle = (angle + 2) % 360
                with self._lock:
                    self._samples += 1
                    self._quality = min(100.0, self._data.point_count() / 50.0)
                    self._progress = self._quality
                self._sleep(0.05)
        finally:
            with self._lock:
                self._scanning = False
                self._phase = "cancelled" if self._cancel_event.is_set() else "complete"
                self._end_time = time.time()

    def _physical_capture_loop(self) -> None:
        laser_counts = {side: 0 for side in self._LASER_SIDES}
        camera_counts = {name: 0 for name in self._REQUIRED_CAMERAS}
        completed = False
        try:
            self._move_to_saved_pose()
            start_positions = self._motor_positions()
            trajectory = self._trajectory(start_positions)
            total = len(trajectory)
            for index, targets in enumerate(trajectory):
                self._check_cancelled()
                with self._lock:
                    self._phase = "positioning"
                    self._progress = index / total * 100.0
                self._move_axes(targets)
                self._sleep_interruptible(self._milliseconds("settle_ms", 200))
                lidar_distance = self._sample_lidar()
                self._add_lidar_point(lidar_distance, start_positions)

                with self._lock:
                    self._phase = "ambient-capture"
                self._lasers_off()
                ambient = {
                    name: self._capture_camera(name)
                    for name in self._REQUIRED_CAMERAS
                }
                for side in self._LASER_SIDES:
                    self._check_cancelled()
                    self._set_laser(side, True)
                    try:
                        self._sleep_interruptible(self._milliseconds("laser_settle_ms", 100))
                        with self._lock:
                            self._phase = "laser-capture"
                            self._laser_side = side
                        for camera_name in self._REQUIRED_CAMERAS:
                            laser_frame = self._capture_camera(camera_name)
                            if not self._laser_line_detected(laser_frame):
                                continue
                            with self._lock:
                                self._laser_detections[side] += 1
                            points = self._extract_points(
                                camera_name,
                                side,
                                ambient[camera_name],
                                laser_frame,
                                start_positions,
                            )
                            camera_counts[camera_name] += len(points)
                            laser_counts[side] += len(points)
                            color = (1.0, 0.2, 0.2) if side == "left" else (0.3, 0.6, 1.0)
                            with self._lock:
                                for point in points:
                                    self._data.add_point(*point, *color)
                    finally:
                        self._set_laser(side, False)

                with self._lock:
                    self._samples += 1
                    self._progress = (index + 1) / total * 100.0
                    self._quality = min(
                        100.0,
                        self._data.point_count()
                        / max(1, self._positive_int("target_points", 1000))
                        * 100.0,
                    )

            missing = [
                f"{name} produced no calibrated laser points"
                for name, count in camera_counts.items() if count == 0
            ]
            missing.extend(
                f"{side} laser produced no calibrated points"
                for side, count in laser_counts.items() if count == 0
            )
            if missing:
                raise RuntimeError("; ".join(missing))
            if bool(self._config.get("restore_start_pose", True)):
                with self._lock:
                    self._phase = "restoring-position"
                self._move_axes(start_positions)
            completed = True
        except ScanCancelled:
            with self._lock:
                self._phase = "cancelled"
        except Exception as exc:
            logger.exception("Physical scan acquisition failed")
            with self._lock:
                self._error = str(exc)
                self._phase = "error"
            self._cancel_event.set()
        finally:
            try:
                self._lasers_off()
            except Exception:
                logger.exception("Failed to turn lasers off during scan cleanup")
            if not completed:
                self._stop_motors()
            with self._lock:
                self._laser_side = None
                self._scanning = False
                if completed:
                    self._phase = "complete"
                    self._progress = 100.0
                self._end_time = time.time()
            self._release_hardware_reservation()

    def _trajectory(self, origin: Mapping[str, float]) -> list[dict[str, float]]:
        rotation_axis = str(self._config.get("rotation_axis", "y")).lower()
        z_axis = str(self._config.get("z_axis", "z")).lower()
        rotation_steps = self._positive_int("rotation_steps", 3)
        z_levels = self._positive_int("z_levels", 2)
        rotation_step = self._positive_float("rotation_step_mm", 5.0)
        z_step = self._positive_float("z_step_mm", 5.0)
        positions = []
        for z_index in range(z_levels):
            rotation_indexes = range(rotation_steps)
            if z_index % 2:
                rotation_indexes = reversed(range(rotation_steps))
            for rotation_index in rotation_indexes:
                target = dict(origin)
                target[rotation_axis] = origin[rotation_axis] + rotation_index * rotation_step
                target[z_axis] = origin[z_axis] + z_index * z_step
                positions.append(target)
        return positions

    def _prepare_automatic_x_center(self) -> None:
        details = self._x_center_details()
        homing_timeout = self._positive_float("x_homing_timeout_s", 135.0)
        motion_timeout = self._positive_float("motion_timeout_s", 30.0)
        preparation_valid = threading.Event()
        preparation_valid.set()

        def guarded(operation: Callable[[], Any]) -> Any:
            try:
                return operation()
            finally:
                if not preparation_valid.is_set():
                    self._invalidate_x()

        try:
            homed = self._invoke_with_timeout(
                lambda: guarded(lambda: self._motor.home_motor("x")),
                homing_timeout,
                "Axis X homing",
            )
            if not homed:
                raise RuntimeError("axis X homing was rejected or stopped")
            self._check_cancelled()

            target = details["target_mm"]
            move_to = getattr(self._motor, "move_motor_to", None)
            if callable(move_to):
                move = lambda: move_to("x", target)
            else:
                current = float(
                    self._motor.get_motor_status()
                    .get("positions", {})
                    .get("x", details["position_min_mm"])
                )
                move = lambda: self._motor.move_motor("x", target - current)
            centered = self._invoke_with_timeout(
                lambda: guarded(move),
                motion_timeout,
                "Axis X centering",
            )
            if not centered:
                raise RuntimeError("axis X centering was rejected or stopped")

            status = self._motor.get_motor_status()
            actual = float(status.get("positions", {}).get("x", float("nan")))
            tolerance = self._positive_float("position_tolerance_mm", 0.05)
            if (
                not bool(status.get("homed", {}).get("x", False))
                or not math.isfinite(actual)
                or abs(actual - target) > tolerance
            ):
                raise RuntimeError(
                    f"axis X did not confirm centered position {target:.2f} mm"
                )
            with self._lock:
                self._axis_position["x"] = actual
                self._motion_fault = None
                self._motor_preparation = {
                    "homed": True,
                    **details,
                    "actual_mm": actual,
                }
        except Exception:
            preparation_valid.clear()
            self._stop_and_invalidate_x()
            raise

    def _stop_and_invalidate_x(self) -> None:
        try:
            stopped = self._motor.stop_motor("x")
            if not stopped:
                with self._lock:
                    self._motion_fault = (
                        "Axis X emergency stop was rejected; complete a successful manual "
                        "X home before another scan"
                    )
        except Exception:
            logger.exception("Failed to stop X after automatic preparation failure")
            with self._lock:
                self._motion_fault = (
                    "Axis X emergency stop failed; complete a successful manual X home "
                    "before another scan"
                )
        self._invalidate_x()

    def _invalidate_x(self) -> None:
        invalidate = getattr(self._motor, "invalidate_motor_position", None)
        if callable(invalidate):
            try:
                invalidate("x")
            except Exception:
                logger.exception("Failed to invalidate X after automatic preparation failure")

    def clear_motion_fault(self, axis: str) -> None:
        """Clear quarantine only after a successful explicit X/all-axis home."""
        if axis.lower() in {"x", "all"}:
            with self._lock:
                self._motion_fault = None

    def has_outstanding_operations(self) -> bool:
        """Return whether a timed operation still owns hardware."""
        with self._lock:
            self._operation_threads = {
                thread for thread in self._operation_threads if thread.is_alive()
            }
            return bool(self._operation_threads)

    def _move_to_saved_pose(self) -> None:
        pose_name = str(self._config.get("scan_pose_camera", "pi"))
        pose = (self._saved_poses_provider() or {}).get(pose_name)
        if not isinstance(pose, Mapping):
            raise RuntimeError(f"Saved scan pose '{pose_name}' disappeared after preflight")
        pose = dict(pose)
        if self._automatic_x_center_enabled():
            pose["x"] = self._x_center_details()["target_mm"]
        with self._lock:
            self._phase = "moving-to-scan-pose"
        self._move_axes({axis: float(pose[axis]) for axis in ("x", "y", "z")})

    def _move_axes(self, targets: Mapping[str, float]) -> None:
        current = self._motor_positions()
        timeout = self._positive_float("motion_timeout_s", 30.0)
        for axis in ("x", "y", "z"):
            if axis not in targets:
                continue
            self._check_cancelled()
            target = float(targets[axis])
            self._require_target_in_limits(axis, target)
            distance = target - current[axis]
            if abs(distance) < 1e-6:
                continue
            result = self._invoke_with_timeout(
                lambda axis=axis, distance=distance: self._motor.move_motor(axis, distance),
                timeout,
                f"Axis {axis.upper()} motion",
            )
            if not result:
                raise RuntimeError(
                    f"Axis {axis.upper()} move to {target:.2f} mm was rejected or stopped"
                )
            current[axis] = target
            with self._lock:
                self._axis_position = dict(current)

    def _require_target_in_limits(self, axis: str, target: float) -> None:
        limits = self._config.get("axis_limits_mm", {})
        axis_limits = limits.get(axis) if isinstance(limits, Mapping) else None
        if not isinstance(axis_limits, Mapping):
            raise RuntimeError(f"Axis {axis.upper()} has no configured travel limits")
        try:
            low = float(axis_limits["min"])
            high = float(axis_limits["max"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Axis {axis.upper()} travel limits are invalid") from exc
        if (
            not math.isfinite(target)
            or not math.isfinite(low)
            or not math.isfinite(high)
            or high <= low
            or not low <= target <= high
        ):
            raise RuntimeError(
                f"Axis {axis.upper()} target {target:.2f} mm is outside configured "
                f"limits [{low:.2f}, {high:.2f}]"
            )

    def _motor_positions(self) -> dict[str, float]:
        status = self._motor.get_motor_status()
        positions = {
            axis: float(status.get("positions", {}).get(axis, 0.0))
            for axis in ("x", "y", "z")
        }
        with self._lock:
            self._axis_position = positions
        return positions

    def _capture_camera(self, name: str) -> bytes:
        camera = self._cameras[name]
        frame = self._invoke_with_timeout(
            camera.capture_jpeg,
            self._positive_float("capture_timeout_s", 5.0),
            f"Camera '{name}' capture",
        )
        if not frame:
            raise RuntimeError(
                f"Camera '{name}' returned no frame: {getattr(camera, 'last_error', 'unknown error')}"
            )
        with self._lock:
            self._camera_frames += 1
        return frame

    def _sample_lidar(self) -> float:
        count = self._positive_int("lidar_samples_per_pose", 3)
        values = []
        for _ in range(count):
            self._check_cancelled()
            value = self._invoke_with_timeout(
                self._lidar.read_distance_mm,
                self._positive_float("lidar_timeout_s", 1.0),
                "TF-Luna sample",
            )
            if value is not None:
                values.append(float(value))
            self._sleep_interruptible(0.02)
        if not values:
            raise RuntimeError("TF-Luna returned no valid samples at the current scan position")
        distance = float(np.median(values))
        min_distance, max_distance = self._lidar_limits()
        if not self._lidar_distance_valid(distance):
            raise RuntimeError(
                f"TF-Luna distance {distance:.1f} mm is outside calibrated range "
                f"[{min_distance:.1f}, {max_distance:.1f}]"
            )
        with self._lock:
            self._lidar_samples += len(values)
        return distance

    def _lidar_limits(self) -> tuple[float, float]:
        lidar_cfg = self._calibration.get("lidar", {})
        return (
            float(lidar_cfg.get("min_distance_mm", 20.0)),
            float(lidar_cfg.get("max_distance_mm", 8000.0)),
        )

    def _lidar_distance_valid(self, distance: float) -> bool:
        low, high = self._lidar_limits()
        return math.isfinite(distance) and low <= distance <= high

    def _read_lidar_sample(self) -> float | None:
        return self._invoke_with_timeout(
            self._lidar.read_distance_mm,
            self._positive_float("lidar_timeout_s", 1.0),
            "TF-Luna preflight sample",
        )

    def _add_lidar_point(
        self,
        distance_mm: float,
        trajectory_origin: Mapping[str, float],
    ) -> None:
        transform = np.asarray(self._calibration["lidar"]["lidar_to_scanner"], dtype=float)
        origin = transform[:3, 3]
        direction = transform[:3, :3] @ np.array([0.0, 0.0, 1.0])
        direction /= np.linalg.norm(direction)
        point = origin + direction * distance_mm
        point = self._apply_carriage_translation(
            point, self._calibration["lidar"], trajectory_origin
        )
        point = self._normalize_turntable_point(point, trajectory_origin)
        with self._lock:
            self._data.add_point(*point.tolist(), 1.0, 0.85, 0.2)

    def _extract_points(
        self,
        camera_name: str,
        laser_side: str,
        ambient_jpeg: bytes,
        laser_jpeg: bytes,
        trajectory_origin: Mapping[str, float],
    ) -> list[list[float]]:
        ambient = cv2.imdecode(np.frombuffer(ambient_jpeg, np.uint8), cv2.IMREAD_COLOR)
        laser = cv2.imdecode(np.frombuffer(laser_jpeg, np.uint8), cv2.IMREAD_COLOR)
        if ambient is None or laser is None or ambient.shape != laser.shape:
            raise RuntimeError(f"Camera '{camera_name}' produced undecodable or mismatched frames")

        red_delta = laser[:, :, 2].astype(np.int16) - ambient[:, :, 2].astype(np.int16)
        red_excess = (
            laser[:, :, 2].astype(np.int16)
            - np.maximum(laser[:, :, 1], laser[:, :, 0]).astype(np.int16)
        )
        threshold = self._positive_int("laser_delta_threshold", 35)
        mask = (red_delta >= threshold) & (red_excess >= threshold // 2)
        row_stride = self._positive_int("laser_row_stride", 4)
        max_points = self._positive_int("max_points_per_frame", 300)
        pixels: list[tuple[float, float]] = []
        for row in range(0, mask.shape[0], row_stride):
            columns = np.flatnonzero(mask[row])
            if columns.size:
                pixels.append((float(np.median(columns)), float(row)))
                if len(pixels) >= max_points:
                    break

        camera_cfg = self._calibration["cameras"][camera_name]
        intrinsic = np.asarray(camera_cfg["intrinsic_matrix"], dtype=float)
        distortion = np.asarray(camera_cfg["distortion_coefficients"], dtype=float)
        transform = np.asarray(camera_cfg["camera_to_scanner"], dtype=float)
        origin = transform[:3, 3]
        plane = self._calibration["laser_planes"][laser_side]
        normal = np.asarray(plane["normal"], dtype=float)
        normal /= np.linalg.norm(normal)
        offset = float(plane["offset_mm"])
        points = []
        for u, v in pixels:
            normalized = cv2.undistortPoints(
                np.array([[[u, v]]], dtype=np.float64),
                intrinsic,
                distortion,
            ).reshape(2)
            ray_camera = np.array([normalized[0], normalized[1], 1.0])
            direction = transform[:3, :3] @ ray_camera
            direction /= np.linalg.norm(direction)
            translated_origin = self._apply_carriage_translation(
                origin, camera_cfg, trajectory_origin
            )
            denominator = float(np.dot(normal, direction))
            if abs(denominator) < 1e-9:
                continue
            ray_distance = -(float(np.dot(normal, translated_origin)) + offset) / denominator
            if (
                ray_distance <= 0
                or ray_distance > self._positive_float("max_triangulation_distance_mm", 2000.0)
            ):
                continue
            point = translated_origin + direction * ray_distance
            point = self._normalize_turntable_point(point, trajectory_origin)
            points.append(point.tolist())
        return points

    def _laser_line_detected(self, laser_jpeg: bytes) -> bool:
        """Reuse the shared alignment analyzer before calibrated triangulation."""
        if self._laser_line_analyzer is None:
            return True
        try:
            result = self._laser_line_analyzer(laser_jpeg)
        except Exception:
            logger.exception("Laser-line analyzer failed during acquisition")
            return False
        return bool(result.get("analysis_available") and result.get("line_detected"))

    def _apply_carriage_translation(
        self,
        point: np.ndarray,
        sensor_config: Mapping[str, Any],
        _trajectory_origin: Mapping[str, float],
    ) -> np.ndarray:
        axis = sensor_config.get("carriage_axis")
        if axis not in {"x", "y", "z"}:
            return np.array(point, dtype=float)
        direction = np.asarray(
            sensor_config.get("carriage_direction", [0.0, 0.0, 1.0]),
            dtype=float,
        )
        positions = self._axis_position
        displacement = positions[axis] - float(
            sensor_config["reference_axis_position_mm"]
        )
        return np.array(point, dtype=float) + direction * displacement

    def _normalize_turntable_point(
        self,
        point: np.ndarray,
        trajectory_origin: Mapping[str, float],
    ) -> np.ndarray:
        turntable = self._calibration["turntable"]
        center = np.asarray(turntable["center_mm"], dtype=float)
        axis = np.asarray(turntable["axis"], dtype=float)
        axis /= np.linalg.norm(axis)
        rotation_axis = str(self._config.get("rotation_axis", "y")).lower()
        travel = self._axis_position[rotation_axis] - float(trajectory_origin[rotation_axis])
        angle = -2.0 * math.pi * travel / float(turntable["mm_per_revolution"])
        vector = np.asarray(point, dtype=float) - center
        rotated = (
            vector * math.cos(angle)
            + np.cross(axis, vector) * math.sin(angle)
            + axis * np.dot(axis, vector) * (1.0 - math.cos(angle))
        )
        return center + rotated

    def _set_laser(self, side: str, enabled: bool) -> None:
        method = self._gpio.laser_on if enabled else self._gpio.laser_off
        if not method(side):
            raise RuntimeError(f"Failed to turn laser '{side}' {'on' if enabled else 'off'}")
        with self._lock:
            self._laser_side = side if enabled else None

    def _lasers_off(self) -> None:
        failures = []
        if self._gpio is None:
            return
        for side in self._LASER_SIDES:
            try:
                if not self._gpio.laser_off(side):
                    failures.append(side)
            except Exception:
                failures.append(side)
        with self._lock:
            self._laser_side = None
        if failures:
            raise RuntimeError(f"Failed to force lasers OFF: {', '.join(failures)}")

    def _stop_motors(self) -> None:
        if self._motor is None:
            return
        try:
            if not self._motor.stop_motor("all"):
                logger.error("STM32 rejected emergency STOP ALL")
        except Exception:
            logger.exception("Emergency motor stop failed")

    def _emergency_cleanup(self) -> None:
        try:
            self._lasers_off()
        except Exception:
            logger.exception("Emergency laser shutdown failed")
        self._stop_motors()

    def _release_hardware_reservation(self) -> None:
        with self._lock:
            if not self._hardware_reserved:
                return
            outstanding = [
                thread for thread in self._operation_threads if thread.is_alive()
            ]
            self._operation_threads = set(outstanding)
            if outstanding:
                if (
                    self._reservation_release_thread is None
                    or not self._reservation_release_thread.is_alive()
                ):
                    release_thread = threading.Thread(
                        target=self._wait_and_release_hardware,
                        args=(outstanding,),
                        name="scan-hardware-quarantine",
                        daemon=True,
                    )
                    self._reservation_release_thread = release_thread
                    release_thread.start()
                return
            self._hardware_reserved = False
        if self._hardware_reservation is not None:
            self._hardware_reservation.release()

    def _wait_and_release_hardware(
        self,
        operations: list[threading.Thread],
    ) -> None:
        for operation in operations:
            operation.join()
        with self._lock:
            self._reservation_release_thread = None
        self._release_hardware_reservation()

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise ScanCancelled("Scan cancelled")

    def _sleep_interruptible(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self._cancel_event.wait(seconds):
            raise ScanCancelled("Scan cancelled")

    def _invoke_with_timeout(
        self,
        operation: Callable[[], Any],
        timeout_s: float,
        label: str,
    ) -> Any:
        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def run() -> None:
            try:
                outcome["value"] = operation()
            except Exception as exc:
                outcome["error"] = exc
            finally:
                with self._lock:
                    self._operation_threads.discard(threading.current_thread())
                completed.set()

        thread = threading.Thread(target=run, name=f"scan-{label}", daemon=True)
        with self._lock:
            self._operation_threads.add(thread)
        thread.start()
        deadline = time.monotonic() + timeout_s
        while not completed.wait(min(0.05, max(0.0, deadline - time.monotonic()))):
            self._check_cancelled()
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{label} timed out after {timeout_s:.1f}s")
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def _positive_float(self, name: str, default: float) -> float:
        value = float(self._config.get(name, default))
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")
        return value

    def _positive_int(self, name: str, default: int) -> int:
        value = int(self._config.get(name, default))
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")
        return value

    def _milliseconds(self, name: str, default: int) -> float:
        value = float(self._config.get(name, default))
        if value < 0:
            raise ValueError(f"{name} cannot be negative")
        return value / 1000.0

    # ------------------------------------------------------------------
    # Status / data
    # ------------------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            scanning = self._scanning
        readiness = (
            {"ready": True, "mode": self.mode, "blockers": []}
            if scanning
            else self.readiness(probe=False)
        )
        with self._lock:
            if self._start_time:
                end = time.time() if self._scanning else self._end_time
                elapsed = max(0.0, end - self._start_time)
            else:
                elapsed = 0.0
            return {
                "scanning": self._scanning,
                "mode": self.mode,
                "simulation": self._simulation,
                "data_source": "synthetic" if self._simulation else "physical",
                "ready": readiness["ready"],
                "preflight_blockers": readiness["blockers"],
                "phase": self._phase,
                "progress": round(self._progress, 1),
                "axis_position": dict(self._axis_position),
                "motor_preparation": (
                    dict(self._motor_preparation)
                    if self._motor_preparation is not None
                    else None
                ),
                "laser_side": self._laser_side,
                "samples": self._samples,
                "camera_frames": self._camera_frames,
                "lidar_samples": self._lidar_samples,
                "laser_detections": dict(self._laser_detections),
                "points": self._data.point_count(),
                "elapsed_s": round(elapsed, 1),
                "quality": round(self._quality, 1),
                "error": self._error,
            }

    def get_pointcloud(self) -> dict:
        with self._lock:
            return self._data.as_dict()


# ---------------------------------------------------------------------------
# 3D Reconstruction
# ---------------------------------------------------------------------------

class ReconstructionEngine:
    """Converts a ScanData point cloud into a mesh and exports STL/AMF.

    Reconstruction (Poisson surface fitting) is expensive and, on a
    Raspberry Pi 4, can take tens of seconds. To keep the HTTP API
    responsive, the heavy work runs on a background thread; ``reconstruct``
    returns almost immediately and callers poll ``status()`` for progress.
    """

    #: Default Poisson octree depth. Lower depth = coarser mesh but much
    #: faster reconstruction; depth=8 (the Open3D default) is unsuitable
    #: for a Raspberry Pi 4 where it can block for 30-60s.
    DEFAULT_DEPTH = 6

    def __init__(self, scan_session: ScanSession):
        self._session = scan_session
        self._last_stl: Optional[bytes] = None
        self._last_amf: Optional[bytes] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._in_progress = False
        self._cancel_event = threading.Event()
        self._last_result: dict = {"ok": False, "stl_size": 0, "amf_size": 0, "error": ""}

    def reconstruct(self, depth: int = DEFAULT_DEPTH, wait: bool = False) -> dict:
        """Kick off (or wait for) reconstruction.

        Returns immediately with ``{"ok": True, "in_progress": True, ...}``
        once the background job has started, unless ``wait`` is True (used
        by tests) or Open3D is unavailable / there are not enough points,
        in which case the fast synchronous paths are used.
        """
        with self._lock:
            if self._in_progress:
                return {"ok": True, "in_progress": True, "started": False,
                         "stl_size": 0, "amf_size": 0, "error": "Reconstruction already in progress"}

        pc_dict = self._session.get_pointcloud()
        points = pc_dict.get("points", [])

        if len(points) < 100:
            return {"ok": False, "in_progress": False, "stl_size": 0, "amf_size": 0,
                    "error": f"Not enough points ({len(points)} < 100)"}

        if not _O3D_AVAILABLE:
            self._last_stl = self._points_to_ascii_stl(points)
            self._last_amf = b'<?xml version="1.0"?><amf></amf>'
            result = {
                "ok": True,
                "in_progress": False,
                "stl_size": len(self._last_stl),
                "amf_size": len(self._last_amf),
                "error": "Open3D unavailable - grid triangulation used",
            }
            with self._lock:
                self._last_result = result
            return result

        with self._lock:
            self._in_progress = True
            self._cancel_event = threading.Event()
        cancel_event = self._cancel_event
        thread = threading.Thread(
            target=self._reconstruct_worker,
            args=(pc_dict, depth, cancel_event),
            daemon=True,
        )
        self._thread = thread
        thread.start()

        if wait:
            thread.join()
            with self._lock:
                return dict(self._last_result)

        return {"ok": True, "in_progress": True, "started": True,
                "stl_size": 0, "amf_size": 0, "error": ""}

    def cancel(self) -> None:
        """Request cancellation of an in-progress reconstruction."""
        with self._lock:
            self._cancel_event.set()

    def status(self) -> dict:
        """Return the current reconstruction progress/result."""
        with self._lock:
            return {"in_progress": self._in_progress, "result": dict(self._last_result)}

    def _reconstruct_worker(self, pc_dict: dict, depth: int, cancel_event: threading.Event) -> None:
        try:
            if cancel_event.is_set():
                return
            points = pc_dict.get("points", [])
            pts = np.array(points, dtype=np.float64)
            colors_list = pc_dict.get("colors", [])
            has_colors = len(colors_list) == len(points)

            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(pts)
            if has_colors:
                pcd.colors = o3d.utility.Vector3dVector(np.array(colors_list, dtype=np.float64))

            # Voxel downsample for performance
            pcd = pcd.voxel_down_sample(voxel_size=2.0)
            if cancel_event.is_set():
                return

            # Normal estimation
            pcd.estimate_normals(
                o3d.geometry.KDTreeSearchParamHybrid(radius=10.0, max_nn=30)
            )
            pcd.orient_normals_consistent_tangent_plane(100)
            if cancel_event.is_set():
                return

            # Poisson reconstruction (reduced depth keeps this fast on RPi4)
            mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                pcd, depth=depth
            )
            if cancel_event.is_set():
                return

            # Remove low-density vertices
            densities_arr = np.asarray(densities)
            threshold = np.percentile(densities_arr, 5)
            vertices_to_remove = densities_arr < threshold
            mesh.remove_vertices_by_mask(vertices_to_remove)
            mesh.compute_vertex_normals()

            # Export STL/AMF directly to memory buffers (no disk I/O)
            last_stl = self._mesh_to_stl_bytes(mesh)
            last_amf = self._stl_to_amf(mesh)

            result = {
                "ok": True,
                "in_progress": False,
                "stl_size": len(last_stl),
                "amf_size": len(last_amf),
                "error": "",
            }
            with self._lock:
                self._last_stl = last_stl
                self._last_amf = last_amf
                self._last_result = result

        except Exception:
            logger.exception("Reconstruction failed")
            with self._lock:
                self._last_result = {"ok": False, "in_progress": False, "stl_size": 0,
                                      "amf_size": 0, "error": "Reconstruction failed"}
        finally:
            with self._lock:
                self._in_progress = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_model(self, fmt: str = "stl") -> Optional[bytes]:
        if fmt == "stl":
            return self._last_stl
        if fmt == "amf":
            return self._last_amf
        return None

    @staticmethod
    def _mesh_to_stl_bytes(mesh) -> bytes:
        """Serialize an Open3D mesh directly to an in-memory ASCII STL.

        Avoids writing to a temporary file and reading it back (double
        disk I/O), which blocks the main thread unnecessarily.
        """
        vertices = np.asarray(mesh.vertices)
        triangles = np.asarray(mesh.triangles)

        buf = io.BytesIO()
        buf.write(b"solid horalscanner\n")
        for tri in triangles:
            v0, v1, v2 = vertices[tri[0]], vertices[tri[1]], vertices[tri[2]]
            normal = np.cross(v1 - v0, v2 - v0)
            norm_len = np.linalg.norm(normal)
            if norm_len > 1e-12:
                normal = normal / norm_len
            else:
                normal = np.zeros(3)
            buf.write(f" facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}\n".encode("ascii"))
            buf.write(b"  outer loop\n")
            for v in (v0, v1, v2):
                buf.write(f"   vertex {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n".encode("ascii"))
            buf.write(b"  endloop\n")
            buf.write(b" endfacet\n")
        buf.write(b"endsolid horalscanner\n")
        return buf.getvalue()

    @staticmethod
    def _stl_to_amf(mesh) -> bytes:
        """Very simple AMF wrapper around triangle mesh geometry."""
        vertices = np.asarray(mesh.vertices)
        triangles = np.asarray(mesh.triangles)

        lines = ['<?xml version="1.0" encoding="utf-8"?>',
                 '<amf unit="millimeter" version="1.1">',
                 ' <object id="1">',
                 '  <mesh>',
                 '   <vertices>']
        for v in vertices:
            lines.append(f'    <vertex><coordinates>'
                         f'<x>{v[0]:.6f}</x><y>{v[1]:.6f}</y><z>{v[2]:.6f}</z>'
                         f'</coordinates></vertex>')
        lines.append('   </vertices>')
        lines.append('   <volume>')
        for t in triangles:
            lines.append(f'    <triangle>'
                         f'<v1>{t[0]}</v1><v2>{t[1]}</v2><v3>{t[2]}</v3>'
                         f'</triangle>')
        lines.append('   </volume>')
        lines.append('  </mesh>')
        lines.append(' </object>')
        lines.append('</amf>')
        return "\n".join(lines).encode("utf-8")

    @staticmethod
    def _points_to_ascii_stl(points, rows: int = 5) -> bytes:
        """Triangulate sequential scan columns into an ASCII STL surface."""
        columns = len(points) // rows
        if columns < 2:
            return b"solid horalscanner\nendsolid horalscanner\n"

        def normal(a, b, c):
            ab = [b[index] - a[index] for index in range(3)]
            ac = [c[index] - a[index] for index in range(3)]
            vector = [
                ab[1] * ac[2] - ab[2] * ac[1],
                ab[2] * ac[0] - ab[0] * ac[2],
                ab[0] * ac[1] - ab[1] * ac[0],
            ]
            length = math.sqrt(sum(value * value for value in vector)) or 1.0
            return [value / length for value in vector]

        lines = ["solid horalscanner"]
        for column in range(columns - 1):
            current = column * rows
            following = (column + 1) * rows
            for row in range(rows - 1):
                faces = (
                    (points[current + row], points[following + row], points[current + row + 1]),
                    (points[following + row], points[following + row + 1], points[current + row + 1]),
                )
                for face in faces:
                    nx, ny, nz = normal(*face)
                    lines.append(f" facet normal {nx:.6f} {ny:.6f} {nz:.6f}")
                    lines.append("  outer loop")
                    for x, y, z in face:
                        lines.append(f"   vertex {x:.6f} {y:.6f} {z:.6f}")
                    lines.append("  endloop")
                    lines.append(" endfacet")
        lines.append("endsolid horalscanner")
        return "\n".join(lines).encode("ascii")
