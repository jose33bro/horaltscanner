"""Automatic, guarded geometric calibration for the physical scanner."""

from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from software.api.checkerboard_detector import find_checkerboard_bounded

try:
    import cv2 as _cv2
except ImportError:  # pragma: no cover - Raspberry Pi dependency
    _cv2 = None


class CalibrationError(RuntimeError):
    """A calibration quality or hardware guard failed."""


class CalibrationCancelled(CalibrationError):
    """The operator cancelled calibration."""


BOARD_COLUMNS = 10
BOARD_ROWS = 6
BOARD_SQUARE_MM = 13.0


def checkerboard_points(
    columns: int = BOARD_COLUMNS,
    rows: int = BOARD_ROWS,
    square_mm: float = BOARD_SQUARE_MM,
) -> np.ndarray:
    """Return centered checkerboard inner corners in its physical board frame."""
    if columns < 2 or rows < 2 or not math.isfinite(square_mm) or square_mm <= 0:
        raise ValueError("checkerboard dimensions and square size must be positive")
    points = np.zeros((columns * rows, 3), dtype=np.float32)
    grid = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2).astype(np.float32)
    grid[:, 0] -= (columns - 1) / 2.0
    grid[:, 1] -= (rows - 1) / 2.0
    points[:, :2] = grid * square_mm
    return points


def validate_view_diversity(
    views: list[Mapping[str, Any]],
    *,
    minimum_views: int,
    minimum_center_span: float = 0.04,
    minimum_scale_span: float = 0.04,
    minimum_angle_span_deg: float = 5.0,
) -> dict[str, float]:
    """Reject repeated near-identical views before invoking OpenCV."""
    if len(views) < minimum_views:
        raise CalibrationError(f"insufficient accepted views: {len(views)} < {minimum_views}")
    centers: list[np.ndarray] = []
    scales: list[float] = []
    angles: list[float] = []
    for view in views:
        corners = np.asarray(view["corners"], dtype=float).reshape(-1, 2)
        width, height = view["image_size"]
        if corners.shape[0] < 4 or width <= 0 or height <= 0:
            raise CalibrationError("invalid checkerboard view")
        centers.append(corners.mean(axis=0) / np.array([width, height]))
        span = np.ptp(corners, axis=0)
        scales.append(float(span[0] * span[1] / (width * height)))
        vector = corners[-1] - corners[0]
        angles.append(math.degrees(math.atan2(float(vector[1]), float(vector[0]))))
    center_array = np.asarray(centers)
    center_span = float(max(np.ptp(center_array[:, 0]), np.ptp(center_array[:, 1])))
    scale_span = float(np.ptp(scales))
    angle_span = float(np.ptp(angles))
    if center_span < minimum_center_span:
        raise CalibrationError("insufficient checkerboard position diversity")
    if scale_span < minimum_scale_span:
        raise CalibrationError("insufficient checkerboard distance/scale diversity")
    if angle_span < minimum_angle_span_deg:
        raise CalibrationError("insufficient checkerboard angle diversity")
    return {
        "center_span": center_span,
        "scale_span": scale_span,
        "angle_span_deg": angle_span,
    }


def fit_plane_robust(points: Any, *, minimum_points: int = 20) -> tuple[np.ndarray, float, dict]:
    """Fit ``normal dot point + offset = 0`` with two MAD rejection passes."""
    values = np.asarray(points, dtype=float)
    if values.ndim != 2 or values.shape[1] != 3 or len(values) < minimum_points:
        raise CalibrationError(f"insufficient laser plane points: {len(values)} < {minimum_points}")
    if not bool(np.isfinite(values).all()):
        raise CalibrationError("laser plane points contain non-finite values")
    coordinate_center = np.median(values, axis=0)
    radial = np.linalg.norm(values - coordinate_center, axis=1)
    radial_median = float(np.median(radial))
    radial_mad = float(np.median(np.abs(radial - radial_median)))
    radial_limit = radial_median + 6.0 * max(radial_mad, 0.25)
    inliers = values[radial <= radial_limit]
    if len(inliers) < minimum_points:
        raise CalibrationError("robust laser plane fit rejected too many spatial outliers")
    for _ in range(2):
        center = np.median(inliers, axis=0)
        _, _, vh = np.linalg.svd(inliers - center, full_matrices=False)
        normal = vh[-1]
        normal /= np.linalg.norm(normal)
        distances = np.abs((inliers - center) @ normal)
        median = float(np.median(distances))
        mad = float(np.median(np.abs(distances - median)))
        threshold = max(0.25, median + 3.5 * 1.4826 * mad)
        selected = inliers[distances <= threshold]
        if len(selected) < minimum_points:
            raise CalibrationError("robust laser plane fit rejected too many points")
        inliers = selected
    center = inliers.mean(axis=0)
    _, _, vh = np.linalg.svd(inliers - center, full_matrices=False)
    normal = vh[-1]
    normal /= np.linalg.norm(normal)
    offset = -float(np.dot(normal, center))
    residuals = inliers @ normal + offset
    rms = float(np.sqrt(np.mean(residuals ** 2)))
    return normal, offset, {
        "accepted": True,
        "rms_mm": rms,
        "inliers": int(len(inliers)),
        "samples": int(len(values)),
    }


def transform_from_beam(origin_mm: Any, direction: Any) -> np.ndarray:
    """Build a finite scanner transform whose local +Z is the measured beam."""
    origin = np.asarray(origin_mm, dtype=float)
    beam = np.asarray(direction, dtype=float)
    if origin.shape != (3,) or beam.shape != (3,) or not np.isfinite(origin).all():
        raise CalibrationError("TF-Luna origin and direction must be finite 3-vectors")
    norm = float(np.linalg.norm(beam))
    if not math.isfinite(norm) or norm <= 1e-9:
        raise CalibrationError("TF-Luna direction must be non-zero")
    z_axis = beam / norm
    helper = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(helper, z_axis))) > 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    x_axis = np.cross(helper, z_axis)
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    transform = np.eye(4)
    transform[:3, :3] = np.column_stack((x_axis, y_axis, z_axis))
    transform[:3, 3] = origin
    return transform


def validate_calibration_payload(calibration: Mapping[str, Any]) -> None:
    """Validate the persisted geometry and its evidence metadata."""

    def matrix(value: Any, shape: tuple[int, int], label: str) -> np.ndarray:
        result = np.asarray(value, dtype=float)
        if result.shape != shape or not np.isfinite(result).all():
            raise CalibrationError(f"{label} must be a finite {shape[0]}x{shape[1]} matrix")
        if shape[0] == shape[1] and abs(float(np.linalg.det(result))) <= 1e-12:
            raise CalibrationError(f"{label} is singular")
        return result

    board = calibration.get("checkerboard", {})
    if (
        not isinstance(board, Mapping)
        or board.get("board_columns") != BOARD_COLUMNS
        or board.get("board_rows") != BOARD_ROWS
        or not math.isclose(
            float(board.get("square_size_mm", math.nan)),
            BOARD_SQUARE_MM,
            rel_tol=0,
            abs_tol=1e-9,
        )
    ):
        raise CalibrationError(
            "calibration checkerboard must be exactly 10x6 inner corners with 13mm squares"
        )

    cameras = calibration.get("cameras", {})
    for name in ("pi", "usb"):
        camera = cameras.get(name, {})
        matrix(camera.get("intrinsic_matrix"), (3, 3), f"{name} intrinsic_matrix")
        transform = matrix(camera.get("camera_to_scanner"), (4, 4), f"{name} camera_to_scanner")
        if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-6):
            raise CalibrationError(f"{name} camera_to_scanner is not homogeneous")
        distortion = np.asarray(camera.get("distortion_coefficients"), dtype=float).reshape(-1)
        if len(distortion) < 4 or not np.isfinite(distortion).all():
            raise CalibrationError(f"{name} distortion coefficients are missing")
        quality = camera.get("quality", {})
        rms = float(quality.get("rms_px", math.inf))
        maximum_rms = float(quality.get("maximum_rms_px", math.nan))
        translation_rms = float(quality.get("extrinsic_translation_rms_mm", math.inf))
        maximum_translation = float(quality.get("maximum_extrinsic_rms_mm", math.nan))
        rotation_rms = float(quality.get("extrinsic_rotation_rms_deg", math.inf))
        maximum_rotation = float(quality.get("maximum_extrinsic_rms_deg", math.nan))
        if (
            not quality.get("accepted")
            or not all(
                math.isfinite(value)
                for value in (
                    rms,
                    maximum_rms,
                    translation_rms,
                    maximum_translation,
                    rotation_rms,
                    maximum_rotation,
                )
            )
            or maximum_rms <= 0
            or maximum_translation <= 0
            or maximum_rotation <= 0
            or rms > maximum_rms
            or translation_rms > maximum_translation
            or rotation_rms > maximum_rotation
        ):
            raise CalibrationError(f"{name} camera quality is not accepted")

    for side in ("left", "right"):
        plane = calibration.get("laser_planes", {}).get(side, {})
        normal = np.asarray(plane.get("normal"), dtype=float)
        if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) <= 1e-9:
            raise CalibrationError(f"{side} laser plane is invalid")
        if not math.isfinite(float(plane.get("offset_mm", math.nan))):
            raise CalibrationError(f"{side} laser plane offset is invalid")
        quality = plane.get("quality", {})
        rms = float(quality.get("rms_mm", math.inf))
        maximum = float(quality.get("maximum_rms_mm", math.nan))
        if (
            not quality.get("accepted")
            or not math.isfinite(rms)
            or not math.isfinite(maximum)
            or maximum <= 0
            or rms > maximum
        ):
            raise CalibrationError(f"{side} laser plane quality is not accepted")

    turntable = calibration.get("turntable", {})
    circumference = float(turntable.get("mm_per_revolution", math.nan))
    if not math.isfinite(circumference) or circumference <= 0:
        raise CalibrationError("turntable circumference is invalid")
    diameter = float(turntable.get("diameter_mm", math.nan))
    if (
        not math.isfinite(diameter)
        or diameter <= 0
        or not math.isclose(circumference, math.pi * diameter, rel_tol=1e-8, abs_tol=1e-6)
    ):
        raise CalibrationError("turntable circumference does not match measured diameter")
    if turntable.get("source") != "measured_diameter":
        raise CalibrationError("turntable circumference source is not recorded")
    if not turntable.get("quality", {}).get("accepted"):
        raise CalibrationError("turntable quality is not accepted")

    lidar = calibration.get("lidar", {})
    transform = matrix(lidar.get("lidar_to_scanner"), (4, 4), "TF-Luna lidar_to_scanner")
    if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-6):
        raise CalibrationError("TF-Luna transform is not homogeneous")
    if lidar.get("source") != "operator_measured_origin_direction":
        raise CalibrationError("TF-Luna transform source is not recorded")
    lidar_quality = lidar.get("quality", {})
    lidar_rms = float(lidar_quality.get("rms_mm", math.inf))
    lidar_maximum = float(lidar_quality.get("maximum_rms_mm", math.nan))
    if (
        not lidar_quality.get("accepted")
        or not math.isfinite(lidar_rms)
        or not math.isfinite(lidar_maximum)
        or lidar_maximum <= 0
        or lidar_rms > lidar_maximum
    ):
        raise CalibrationError("TF-Luna quality is not accepted")

    x_scale = calibration.get("x_scale_validation", {})
    measured = float(x_scale.get("measured_mm_per_commanded_mm", math.nan))
    expected = float(x_scale.get("expected_mm_per_commanded_mm", math.nan))
    tolerance = float(x_scale.get("tolerance_fraction", math.nan))
    repeatability = float(x_scale.get("repeatability_rms_mm", math.inf))
    maximum_repeatability = float(x_scale.get("maximum_repeatability_mm", math.nan))
    if (
        not x_scale.get("accepted")
        or not all(
            math.isfinite(value)
            for value in (measured, expected, tolerance, repeatability, maximum_repeatability)
        )
        or expected <= 0
        or tolerance < 0
        or maximum_repeatability <= 0
        or abs(measured - expected) > tolerance * expected
        or repeatability > maximum_repeatability
        or x_scale.get("motor_rotation_distance_changed") is not False
    ):
        raise CalibrationError("X scale validation is not accepted")


class AtomicCalibrationStore:
    """Atomic calibration persistence with one known-good rollback backup."""

    def __init__(self, hardware_config_path: str | Path):
        self.path = Path(hardware_config_path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".calibration.bak")
        self.report_path = self.path.with_suffix(self.path.suffix + ".calibration-report.json")

    def _read(self, path: Path | None = None) -> dict:
        with open(path or self.path, encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, calibration: Mapping[str, Any], report: Mapping[str, Any]) -> None:
        validate_calibration_payload(calibration)
        current = self._read()
        updated = copy.deepcopy(current)
        updated["scan_calibration"] = copy.deepcopy(dict(calibration))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        backup_tmp = self.backup_path.with_suffix(self.backup_path.suffix + ".new")
        config_tmp = self.path.with_suffix(self.path.suffix + ".new")
        report_tmp = self.report_path.with_suffix(self.report_path.suffix + ".new")
        try:
            self._write_json(backup_tmp, current)
            self._write_json(config_tmp, updated)
            self._write_json(report_tmp, dict(report))
            os.replace(backup_tmp, self.backup_path)
            os.replace(config_tmp, self.path)
            os.replace(report_tmp, self.report_path)
        finally:
            for temporary in (backup_tmp, config_tmp, report_tmp):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def rollback(self) -> dict:
        if not self.backup_path.exists():
            raise CalibrationError("no calibration backup is available")
        backup = self._read(self.backup_path)
        temporary = self.path.with_suffix(self.path.suffix + ".rollback")
        try:
            self._write_json(temporary, backup)
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return backup.get("scan_calibration", {})

    def report(self) -> dict:
        if not self.report_path.exists():
            raise CalibrationError("no calibration report is available")
        return self._read(self.report_path)

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())


class GeometricCalibrationService:
    """Run the complete calibration trajectory on one background thread."""

    PHASES = (
        "preflight",
        "framing",
        "camera-views",
        "intrinsics",
        "extrinsics",
        "x-scale",
        "laser-planes",
        "lidar",
        "validation",
        "persisting",
        "complete",
    )

    def __init__(
        self,
        *,
        motor_driver: Any,
        gpio_driver: Any,
        cameras: Mapping[str, Any],
        lidar_driver: Any,
        hardware_reservation: Any,
        store: AtomicCalibrationStore,
        config: Mapping[str, Any],
        on_saved: Callable[[Mapping[str, Any]], None] | None = None,
        cv_module: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._motor = motor_driver
        self._gpio = gpio_driver
        self._cameras = dict(cameras)
        self._lidar = lidar_driver
        self._reservation = hardware_reservation
        self._store = store
        self._config = dict(config)
        self._on_saved = on_saved
        self._cv = cv_module if cv_module is not None else _cv2
        self._sleep = sleep
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False
        self._status = self._new_status()
        self._report: dict[str, Any] = {}
        self._reference_pose = dict(
            self._config.get("starting_pose_mm", {"x": 185, "y": 0, "z": 25})
        )

    def _new_status(self) -> dict[str, Any]:
        return {
            "active": False,
            "phase": "idle",
            "step": "Ready",
            "progress": 0.0,
            "accepted_views": {"pi": 0, "usb": 0},
            "rejected_views": {"pi": 0, "usb": 0},
            "metrics": {},
            "error": None,
            "blockers": [],
            "starting_pose_validated": None,
        }

    def status(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._status)

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def readiness(
        self,
        options: Mapping[str, Any] | None = None,
        *,
        probe_devices: bool = False,
    ) -> dict:
        blockers: list[str] = []
        if self._cv is None:
            blockers.append("OpenCV is required for geometric calibration")
        if (
            self._config.get("board_columns") != BOARD_COLUMNS
            or self._config.get("board_rows") != BOARD_ROWS
            or self._config.get("square_size_mm") != BOARD_SQUARE_MM
        ):
            blockers.append(
                "checkerboard configuration must explicitly specify "
                "board_columns=10, board_rows=6, square_size_mm=13"
            )
        if self._motor is None or not getattr(self._motor, "connected", False):
            blockers.append("STM32 motor controller is not connected")
            motor_status = {}
        else:
            try:
                motor_status = self._hardware_call(
                    "motor status",
                    self._motor.get_motor_status,
                    float(self._config.get("motion_timeout_s", 10.0)),
                    check_cancel=False,
                )
            except Exception as exc:
                motor_status = {}
                blockers.append(f"Motor status unavailable: {exc}")
        for axis in ("x", "y", "z"):
            if not motor_status.get("homed", {}).get(axis, False):
                blockers.append(f"Axis {axis.upper()} must be homed")
            if motor_status.get("moving", {}).get(axis, False):
                blockers.append(f"Axis {axis.upper()} is moving")
        if self._gpio is None or getattr(self._gpio, "simulation", True) or not getattr(
            self._gpio, "hardware_available", False
        ):
            blockers.append("physical GPIO laser driver is unavailable")
        for name in ("pi", "usb"):
            camera = self._cameras.get(name)
            if camera is None:
                blockers.append(f"camera '{name}' is unavailable")
            elif probe_devices:
                try:
                    timeout = float(self._config.get("capture_timeout_s", 5.0))
                    if not getattr(camera, "is_open", False) and not self._hardware_call(
                        f"camera '{name}' open",
                        camera.open,
                        timeout,
                        check_cancel=False,
                    ):
                        raise CalibrationError("open failed")
                    frame = self._hardware_call(
                        f"camera '{name}' fresh capture",
                        camera.capture_jpeg,
                        timeout,
                        check_cancel=False,
                    )
                    if not frame:
                        raise CalibrationError("no fresh frame")
                except Exception as exc:
                    blockers.append(f"camera '{name}' preflight failed: {exc}")
        if self._lidar is None:
            blockers.append("TF-Luna is unavailable")
        elif probe_devices:
            try:
                connected = getattr(self._lidar, "connected", None)
                if connected is False:
                    connect = getattr(self._lidar, "connect", None)
                    if connect is None or not self._hardware_call(
                        "TF-Luna connect",
                        connect,
                        float(self._config.get("lidar_timeout_s", 2.0)),
                        check_cancel=False,
                    ):
                        raise CalibrationError("connection failed")
                reading = self._hardware_call(
                    "TF-Luna preflight reading",
                    self._lidar.read_distance_mm,
                    float(self._config.get("lidar_timeout_s", 2.0)),
                    check_cancel=False,
                )
                if reading is None or not math.isfinite(float(reading)) or float(reading) <= 0:
                    raise CalibrationError("no valid distance reading")
            except Exception as exc:
                blockers.append(f"TF-Luna preflight failed: {exc}")
        try:
            self._trajectory(options or {})
        except CalibrationError as exc:
            blockers.append(str(exc))
        lidar_inputs = (options or {}).get("lidar", {})
        if not lidar_inputs.get("origin_mm") or not lidar_inputs.get("direction"):
            blockers.append(
                "TF-Luna measured origin_mm and direction are required; the beam transform "
                "is not fully observable from range readings alone"
            )
        return {"ready": not blockers, "blockers": blockers}

    def preflight(self, options: Mapping[str, Any] | None = None) -> dict:
        """Probe required devices under the shared lock without commanding motion."""
        if self.active:
            return {"ready": False, "blockers": ["geometric calibration is already active"]}
        if not self._reservation.acquire(blocking=False):
            return {"ready": False, "blockers": ["scanner hardware is busy"]}
        try:
            try:
                self._lasers_off()
            except CalibrationError as exc:
                return {"ready": False, "blockers": [str(exc)]}
            return self.readiness(options, probe_devices=True)
        finally:
            self._reservation.release()

    def start(self, options: Mapping[str, Any] | None = None) -> dict:
        options = copy.deepcopy(dict(options or {}))
        with self._lock:
            if self._active:
                raise CalibrationError("geometric calibration is already active")
            if not self._reservation.acquire(blocking=False):
                raise CalibrationError("scanner hardware is busy")
            self._active = True
            self._cancel = threading.Event()
            self._status = self._new_status()
            self._status.update(active=True, phase="preflight", step="Checking safety guards")
            thread = threading.Thread(
                target=self._worker,
                args=(options,),
                name="geometric-calibration",
                daemon=True,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception:
                self._active = False
                self._reservation.release()
                raise
        return self.status()

    def cancel(self) -> dict:
        with self._lock:
            self._cancel.set()
            if self._active:
                self._status["phase"] = "cancelling"
                self._status["step"] = "Stopping motors and forcing lasers off"
        self._safe_outputs()
        return self.status()

    def rollback(self) -> dict:
        if self.active:
            raise CalibrationError("cancel calibration before rollback")
        calibration = self._store.rollback()
        if self._on_saved:
            self._on_saved(calibration)
        return {"rolled_back": True}

    def report(self) -> dict:
        if self._report:
            return copy.deepcopy(self._report)
        return self._store.report()

    def _worker(self, options: dict) -> None:
        start_positions: dict[str, float] | None = None
        try:
            self._lasers_off()
            readiness = self.readiness(options, probe_devices=True)
            if not readiness["ready"]:
                raise CalibrationError("; ".join(readiness["blockers"]))
            start_positions = self._positions()
            poses = self._trajectory(options)
            self._reference_pose = self._starting_pose(options)
            views = self._capture_checkerboard_views(poses)
            calibration = self._solve_cameras(views, options)
            calibration["checkerboard"] = self._board_contract()
            calibration["x_scale_validation"] = self._validate_x_scale(views["pi"], calibration)
            calibration["turntable"] = self._turntable_calibration()
            calibration["laser_planes"] = self._calibrate_lasers(poses, calibration)
            calibration["lidar"] = self._calibrate_lidar(poses, calibration, options["lidar"])
            self._set_phase("validation", "Validating all numeric and residual checks", 92)
            validate_calibration_payload(calibration)
            report = {
                "schema_version": 1,
                "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "checkerboard": self._board_contract(),
                "starting_pose": poses[0],
                "calibration": calibration,
                "metrics": copy.deepcopy(self._status["metrics"]),
            }
            self._set_phase("persisting", "Writing atomic configuration and backup", 97)
            self._store.save(calibration, report)
            if self._on_saved:
                self._on_saved(calibration)
            self._report = report
            if start_positions is not None:
                self._move_to(start_positions)
            self._set_phase("complete", "Calibration saved", 100)
        except CalibrationCancelled:
            self._set_error("cancelled", "Calibration cancelled")
        except Exception as exc:
            self._set_error("error", str(exc))
        finally:
            self._safe_outputs()
            with self._lock:
                self._active = False
                self._status["active"] = False
            self._reservation.release()

    def _trajectory(self, options: Mapping[str, Any]) -> list[dict[str, float]]:
        configured_start = self._starting_pose(options)
        offsets = self._config.get("pose_offsets_mm", [])
        if not offsets:
            offsets = [
                {"x": -10, "y": 0, "z": -5},
                {"x": 0, "y": 10.4719755, "z": 0},
                {"x": 10, "y": 20.943951, "z": 5},
                {"x": -10, "y": 31.4159265, "z": 0},
                {"x": 0, "y": 41.887902, "z": -5},
                {"x": 10, "y": 52.3598776, "z": 0},
                {"x": 0, "y": 62.8318531, "z": 5},
            ]
        limits = self._config.get("axis_limits_mm", {})
        poses: list[dict[str, float]] = []
        for offset in offsets:
            pose = {
                axis: float(configured_start[axis]) + float(offset.get(axis, 0))
                for axis in ("x", "y", "z")
            }
            for axis, target in pose.items():
                axis_limits = limits.get(axis, {})
                low, high = float(axis_limits.get("min", math.nan)), float(
                    axis_limits.get("max", math.nan)
                )
                if not all(math.isfinite(value) for value in (target, low, high)) or not low <= target <= high:
                    raise CalibrationError(
                        f"calibration pose {axis.upper()}={target:.3f} is outside "
                        f"configured limits [{low}, {high}]"
                    )
            poses.append(pose)
        minimum_views = int(self._config.get("minimum_views", 6))
        if len(poses) < minimum_views:
            raise CalibrationError("configured calibration trajectory has insufficient poses")
        return poses

    def _starting_pose(self, options: Mapping[str, Any]) -> dict[str, float]:
        start = dict(self._config.get("starting_pose_mm", {"x": 185, "y": 0, "z": 25}))
        start.update(options.get("starting_pose_mm", {}))
        try:
            return {axis: float(start[axis]) for axis in ("x", "y", "z")}
        except (KeyError, TypeError, ValueError) as exc:
            raise CalibrationError("starting_pose_mm must contain finite X/Y/Z values") from exc

    def _capture_checkerboard_views(self, poses: list[dict[str, float]]) -> dict[str, list[dict]]:
        views: dict[str, list[dict]] = {"pi": [], "usb": []}
        frames_per_pose = int(self._config.get("fresh_frames_per_pose", 3))
        for index, pose in enumerate(poses):
            self._check_cancelled()
            phase = "framing" if index == 0 else "camera-views"
            self._set_phase(
                phase,
                f"Validating checkerboard framing at pose {index + 1}/{len(poses)}",
                5 + 30 * (index + 1) / len(poses),
            )
            self._move_to(pose)
            self._sleep_interruptible(float(self._config.get("settle_s", 0.25)))
            for name in ("pi", "usb"):
                best: dict | None = None
                for _ in range(frames_per_pose):
                    frame = self._capture(name)
                    candidate = self._detect_checkerboard(frame, pose)
                    if candidate and (best is None or candidate["coverage"] > best["coverage"]):
                        best = candidate
                with self._lock:
                    if best is None:
                        self._status["rejected_views"][name] += 1
                    else:
                        views[name].append(best)
                        self._status["accepted_views"][name] += 1
            if index == 0:
                with self._lock:
                    self._status["starting_pose_validated"] = all(views[name] for name in views)
                missing = [name for name in ("pi", "usb") if not views[name]]
                if missing:
                    raise CalibrationError(
                        "starting pose framing rejected for camera(s): "
                        + ", ".join(missing)
                        + "; no multi-pose calibration trajectory was started"
                    )
        minimum = int(self._config.get("minimum_views", 6))
        for name in ("pi", "usb"):
            validate_view_diversity(
                views[name],
                minimum_views=minimum,
                minimum_center_span=float(self._config.get("minimum_center_span", 0.025)),
                minimum_scale_span=float(self._config.get("minimum_scale_span", 0.01)),
                minimum_angle_span_deg=float(self._config.get("minimum_angle_span_deg", 4.0)),
            )
        return views

    def _detect_checkerboard(self, jpeg: bytes, pose: Mapping[str, float]) -> dict | None:
        image = self._cv.imdecode(np.frombuffer(jpeg, np.uint8), self._cv.IMREAD_COLOR)
        if image is None:
            return None
        pattern = (
            int(self._config.get("board_columns", BOARD_COLUMNS)),
            int(self._config.get("board_rows", BOARD_ROWS)),
        )
        detection = find_checkerboard_bounded(
            self._cv,
            image,
            (pattern,),
            max_width=int(self._config.get("checkerboard_max_width", 1280)),
            timeout_s=float(self._config.get("checkerboard_timeout_s", 2.0)),
            allow_ir_glare_fallback=bool(
                self._config.get("checkerboard_ir_glare_fallback", True)
            ),
        )
        if detection.get("timed_out"):
            raise CalibrationError("checkerboard detection timed out")
        if not detection.get("found"):
            return None
        if tuple(detection.get("pattern", ())) != pattern:
            return None
        corners = np.asarray(detection["corners"], dtype=np.float32).reshape(-1, 2)
        height, width = image.shape[:2]
        minimum_margin = float(self._config.get("minimum_frame_margin", 0.04))
        margins = np.array(
            [
                corners[:, 0].min() / width,
                (width - corners[:, 0].max()) / width,
                corners[:, 1].min() / height,
                (height - corners[:, 1].max()) / height,
            ]
        )
        span = np.ptp(corners, axis=0)
        coverage = float(span[0] * span[1] / (width * height))
        if margins.min() < minimum_margin or coverage < float(
            self._config.get("minimum_board_coverage", 0.03)
        ):
            return None
        return {
            "corners": corners,
            "image_size": (width, height),
            "pose": dict(pose),
            "coverage": coverage,
            "jpeg": jpeg,
            "detection_method": detection.get("method"),
            "glare_masked": bool(detection.get("glare_masked")),
        }

    def _solve_cameras(self, views: Mapping[str, list[dict]], options: Mapping[str, Any]) -> dict:
        calibration: dict[str, Any] = {"cameras": {}}
        self._set_phase("intrinsics", "Solving camera intrinsics and distortion", 40)
        for name in ("pi", "usb"):
            camera = self._calibrate_camera_intrinsics(views[name])
            self._set_phase("extrinsics", f"Solving {name} camera scanner transform", 50)
            camera.update(self._calibrate_camera_extrinsics(name, views[name], camera, options))
            if name == "usb":
                camera.update(
                    carriage_axis="z",
                    carriage_direction=[0.0, 0.0, 1.0],
                    reference_axis_position_mm=float(
                        options.get("starting_pose_mm", {}).get(
                            "z", self._config.get("starting_pose_mm", {}).get("z", 25)
                        )
                    ),
                )
            calibration["cameras"][name] = camera
            with self._lock:
                self._status["metrics"][name] = copy.deepcopy(camera["quality"])
        return calibration

    def _calibrate_camera_intrinsics(self, views: list[dict]) -> dict:
        object_points = checkerboard_points(
            int(self._config.get("board_columns", BOARD_COLUMNS)),
            int(self._config.get("board_rows", BOARD_ROWS)),
            float(self._config.get("square_size_mm", BOARD_SQUARE_MM)),
        )
        rms, intrinsic, distortion, rvecs, tvecs = self._cv.calibrateCamera(
            [object_points for _ in views],
            [view["corners"].reshape(-1, 1, 2) for view in views],
            tuple(views[0]["image_size"]),
            None,
            None,
        )
        maximum_rms = float(self._config.get("maximum_camera_rms_px", 1.25))
        if not math.isfinite(float(rms)) or float(rms) > maximum_rms:
            raise CalibrationError(
                f"camera reprojection RMS {float(rms):.3f}px exceeds {maximum_rms:.3f}px"
            )
        per_view = []
        for view, rvec, tvec in zip(views, rvecs, tvecs):
            projected, _ = self._cv.projectPoints(
                object_points, rvec, tvec, intrinsic, distortion
            )
            residual = projected.reshape(-1, 2) - view["corners"].reshape(-1, 2)
            per_view.append(float(np.sqrt(np.mean(np.sum(residual ** 2, axis=1)))))
            view["rvec"], view["tvec"] = rvec, tvec
        quality = {
            "accepted": True,
            "rms_px": float(rms),
            "maximum_rms_px": maximum_rms,
            "views": len(views),
            "per_view_rms_px": per_view,
            "pattern": "10x6_inner_corners",
            "square_size_mm": float(
                self._config.get("square_size_mm", BOARD_SQUARE_MM)
            ),
            "detection_methods": sorted(
                {str(view.get("detection_method", "unknown")) for view in views}
            ),
            "glare_masked_views": sum(bool(view.get("glare_masked")) for view in views),
        }
        return {
            "intrinsic_matrix": np.asarray(intrinsic).tolist(),
            "distortion_coefficients": np.asarray(distortion).reshape(-1).tolist(),
            "quality": quality,
        }

    def _calibrate_camera_extrinsics(
        self,
        name: str,
        views: list[dict],
        camera: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> dict:
        intrinsic = np.asarray(camera["intrinsic_matrix"], dtype=float)
        distortion = np.asarray(camera["distortion_coefficients"], dtype=float)
        board_points = checkerboard_points(
            int(self._config.get("board_columns", BOARD_COLUMNS)),
            int(self._config.get("board_rows", BOARD_ROWS)),
            float(self._config.get("square_size_mm", BOARD_SQUARE_MM)),
        )
        candidates = []
        for view in views:
            ok, rvec, tvec = self._cv.solvePnP(
                board_points,
                view["corners"].reshape(-1, 1, 2),
                intrinsic,
                distortion,
            )
            if not ok:
                continue
            rotation, _ = self._cv.Rodrigues(rvec)
            board_to_camera = np.eye(4)
            board_to_camera[:3, :3] = rotation
            board_to_camera[:3, 3] = np.asarray(tvec).reshape(3)
            scanner_from_board = self._board_to_scanner(view["pose"])
            candidate = scanner_from_board @ np.linalg.inv(board_to_camera)
            if name == "usb":
                reference_z = float(
                    options.get("starting_pose_mm", {}).get(
                        "z", self._config.get("starting_pose_mm", {}).get("z", 25)
                    )
                )
                candidate[:3, 3] -= np.array([0.0, 0.0, view["pose"]["z"] - reference_z])
            candidates.append(candidate)
        if len(candidates) < int(self._config.get("minimum_views", 6)):
            raise CalibrationError(f"{name} extrinsics have insufficient valid PnP views")
        transform, translation_rms, rotation_rms = self._average_transforms(candidates)
        max_translation = float(self._config.get("maximum_extrinsic_rms_mm", 5.0))
        max_rotation = float(self._config.get("maximum_extrinsic_rms_deg", 3.0))
        if translation_rms > max_translation or rotation_rms > max_rotation:
            raise CalibrationError(
                f"{name} extrinsic residual too high: {translation_rms:.2f}mm, "
                f"{rotation_rms:.2f}deg"
            )
        quality = dict(camera["quality"])
        quality.update(
            extrinsic_translation_rms_mm=translation_rms,
            extrinsic_rotation_rms_deg=rotation_rms,
            maximum_extrinsic_rms_mm=max_translation,
            maximum_extrinsic_rms_deg=max_rotation,
            frame="turntable_center_x-radial_y-tangential_z-up",
        )
        return {"camera_to_scanner": transform.tolist(), "quality": quality}

    def _validate_x_scale(self, views: list[dict], calibration: Mapping[str, Any]) -> dict:
        self._set_phase("x-scale", "Validating X scale and repeatability", 60)
        positions = np.asarray([view["pose"]["x"] for view in views], dtype=float)
        unique = np.unique(np.round(positions, 4))
        if len(unique) < 3:
            raise CalibrationError("X scale requires at least three distinct commanded positions")
        translations = np.asarray(
            [np.asarray(view["tvec"], dtype=float).reshape(3) for view in views]
        )
        centered_x = positions - positions.mean()
        centered_t = translations - translations.mean(axis=0)
        slope = (centered_x[:, None] * centered_t).sum(axis=0) / float(
            np.dot(centered_x, centered_x)
        )
        scale = float(np.linalg.norm(slope))
        predicted = translations.mean(axis=0) + centered_x[:, None] * slope
        rms = float(np.sqrt(np.mean(np.sum((translations - predicted) ** 2, axis=1))))
        tolerance = float(self._config.get("x_scale_tolerance_fraction", 0.05))
        maximum_repeatability = float(self._config.get("maximum_x_repeatability_mm", 3.0))
        accepted = abs(scale - 1.0) <= tolerance and rms <= maximum_repeatability
        result = {
            "accepted": accepted,
            "measured_mm_per_commanded_mm": scale,
            "expected_mm_per_commanded_mm": 1.0,
            "tolerance_fraction": tolerance,
            "repeatability_rms_mm": rms,
            "maximum_repeatability_mm": maximum_repeatability,
            "source": "checkerboard_pose_regression",
            "motor_rotation_distance_changed": False,
        }
        if not accepted:
            raise CalibrationError(
                f"X scale validation failed ({scale:.4f} mm/mm, repeatability {rms:.2f}mm); "
                "motor rotation_distance was not changed"
            )
        with self._lock:
            self._status["metrics"]["x_scale"] = copy.deepcopy(result)
        return result

    def _turntable_calibration(self) -> dict:
        diameter = float(self._config.get("turntable_diameter_mm", 200.0))
        circumference = math.pi * diameter
        return {
            "center_mm": [0.0, 0.0, 0.0],
            "axis": [0.0, 0.0, 1.0],
            "diameter_mm": diameter,
            "mm_per_revolution": circumference,
            "source": "measured_diameter",
            "quality": {
                "accepted": True,
                "diameter_source": "operator_measured_turntable",
                "formula": "pi * diameter_mm",
                "derived_mm_per_revolution": circumference,
            },
        }

    def _calibrate_lasers(
        self, poses: list[dict[str, float]], calibration: Mapping[str, Any]
    ) -> dict:
        self._set_phase("laser-planes", "Fitting left and right laser planes", 68)
        samples: dict[str, list[list[float]]] = {"left": [], "right": []}
        try:
            for pose in poses:
                self._check_cancelled()
                self._move_to(pose)
                self._sleep_interruptible(float(self._config.get("settle_s", 0.25)))
                self._lasers_off()
                ambient = {name: self._capture(name) for name in ("pi", "usb")}
                for side in ("left", "right"):
                    self._laser(side, True)
                    try:
                        self._sleep_interruptible(
                            float(self._config.get("laser_settle_s", 0.1))
                        )
                        for name in ("pi", "usb"):
                            laser = self._capture(name)
                            samples[side].extend(
                                self._laser_board_points(
                                    name, side, ambient[name], laser, pose, calibration
                                )
                            )
                    finally:
                        self._laser(side, False)
        finally:
            self._lasers_off()
        result = {}
        maximum_rms = float(self._config.get("maximum_laser_plane_rms_mm", 2.0))
        for side in ("left", "right"):
            normal, offset, quality = fit_plane_robust(
                samples[side],
                minimum_points=int(self._config.get("minimum_laser_points", 30)),
            )
            quality["views"] = len(poses)
            quality["maximum_rms_mm"] = maximum_rms
            if quality["rms_mm"] > maximum_rms:
                raise CalibrationError(
                    f"{side} laser plane RMS {quality['rms_mm']:.2f}mm exceeds "
                    f"{maximum_rms:.2f}mm"
                )
            result[side] = {
                "normal": normal.tolist(),
                "offset_mm": offset,
                "quality": quality,
            }
            with self._lock:
                self._status["metrics"][f"laser_{side}"] = copy.deepcopy(quality)
        return result

    def _laser_board_points(
        self,
        camera_name: str,
        side: str,
        ambient_jpeg: bytes,
        laser_jpeg: bytes,
        pose: Mapping[str, float],
        calibration: Mapping[str, Any],
    ) -> list[list[float]]:
        ambient = self._cv.imdecode(np.frombuffer(ambient_jpeg, np.uint8), self._cv.IMREAD_COLOR)
        laser = self._cv.imdecode(np.frombuffer(laser_jpeg, np.uint8), self._cv.IMREAD_COLOR)
        if ambient is None or laser is None or ambient.shape != laser.shape:
            return []
        delta = laser[:, :, 2].astype(np.int16) - ambient[:, :, 2].astype(np.int16)
        excess = laser[:, :, 2].astype(np.int16) - np.maximum(
            laser[:, :, 1], laser[:, :, 0]
        ).astype(np.int16)
        threshold = int(self._config.get("laser_delta_threshold", 35))
        mask = (delta >= threshold) & (excess >= threshold // 2)
        pixels = []
        for row in range(0, mask.shape[0], int(self._config.get("laser_row_stride", 4))):
            columns = np.flatnonzero(mask[row])
            if columns.size:
                pixels.append([float(np.median(columns)), float(row)])
        if not pixels:
            return []
        camera = calibration["cameras"][camera_name]
        intrinsic = np.asarray(camera["intrinsic_matrix"], dtype=float)
        distortion = np.asarray(camera["distortion_coefficients"], dtype=float)
        normalized = self._cv.undistortPoints(
            np.asarray(pixels, dtype=np.float64).reshape(-1, 1, 2),
            intrinsic,
            distortion,
        ).reshape(-1, 2)
        transform = np.asarray(camera["camera_to_scanner"], dtype=float).copy()
        if camera_name == "usb":
            reference = float(camera.get("reference_axis_position_mm", pose["z"]))
            transform[:3, 3] += np.array([0.0, 0.0, pose["z"] - reference])
        origin = transform[:3, 3]
        board_transform = self._board_to_scanner(pose)
        plane_point = board_transform[:3, 3]
        plane_normal = board_transform[:3, 2]
        result = []
        for x, y in normalized:
            direction = transform[:3, :3] @ np.array([x, y, 1.0])
            direction /= np.linalg.norm(direction)
            denominator = float(np.dot(plane_normal, direction))
            if abs(denominator) <= 1e-9:
                continue
            distance = float(np.dot(plane_normal, plane_point - origin) / denominator)
            if 0 < distance <= float(self._config.get("maximum_ray_distance_mm", 2000)):
                result.append((origin + direction * distance).tolist())
        return result

    def _calibrate_lidar(
        self,
        poses: list[dict[str, float]],
        calibration: Mapping[str, Any],
        inputs: Mapping[str, Any],
    ) -> dict:
        self._set_phase("lidar", "Validating measured TF-Luna beam transform", 84)
        transform = transform_from_beam(inputs.get("origin_mm"), inputs.get("direction"))
        reference_z = float(
            inputs.get("reference_z_mm", self._config.get("starting_pose_mm", {}).get("z", 25))
        )
        residuals = []
        readings = []
        for pose in poses:
            self._check_cancelled()
            self._move_to(pose)
            values = []
            for _ in range(int(self._config.get("lidar_samples_per_pose", 3))):
                value = self._hardware_call(
                    "TF-Luna reading",
                    self._lidar.read_distance_mm,
                    float(self._config.get("lidar_timeout_s", 2.0)),
                )
                if value is not None and math.isfinite(float(value)) and float(value) > 0:
                    values.append(float(value))
            if not values:
                continue
            measured = float(np.median(values))
            current = transform.copy()
            current[:3, 3] += np.array([0.0, 0.0, pose["z"] - reference_z])
            board = self._board_to_scanner(pose)
            origin, direction = current[:3, 3], current[:3, 2]
            denominator = float(np.dot(board[:3, 2], direction))
            if abs(denominator) <= 1e-9:
                continue
            expected = float(
                np.dot(board[:3, 2], board[:3, 3] - origin) / denominator
            )
            if expected > 0:
                readings.append({"pose": pose, "measured_mm": measured, "expected_mm": expected})
                residuals.append(measured - expected)
        minimum = int(self._config.get("minimum_lidar_poses", 3))
        if len(residuals) < minimum:
            raise CalibrationError(
                "TF-Luna beam/board intersection is not observable at enough poses; "
                "verify the measured origin and direction"
            )
        rms = float(np.sqrt(np.mean(np.asarray(residuals) ** 2)))
        maximum = float(self._config.get("maximum_lidar_rms_mm", 20.0))
        if rms > maximum:
            raise CalibrationError(f"TF-Luna geometry RMS {rms:.2f}mm exceeds {maximum:.2f}mm")
        with self._lock:
            self._status["metrics"]["lidar"] = {
                "rms_mm": rms,
                "maximum_rms_mm": maximum,
                "poses": len(residuals),
            }
        return {
            "lidar_to_scanner": transform.tolist(),
            "carriage_axis": "z",
            "carriage_direction": [0.0, 0.0, 1.0],
            "reference_axis_position_mm": reference_z,
            "min_distance_mm": float(inputs.get("min_distance_mm", 20)),
            "max_distance_mm": float(inputs.get("max_distance_mm", 8000)),
            "source": "operator_measured_origin_direction",
            "quality": {
                "accepted": True,
                "rms_mm": rms,
                "maximum_rms_mm": maximum,
                "poses": len(residuals),
                "readings": readings,
                "ir_spot_used": False,
            },
        }

    def _board_to_scanner(self, pose: Mapping[str, float]) -> np.ndarray:
        start_x = float(self._reference_pose["x"])
        diameter = float(self._config.get("turntable_diameter_mm", 200))
        circumference = math.pi * diameter
        angle = 2 * math.pi * float(pose["y"]) / circumference
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        rotate_z = np.array(
            [[cos_a, -sin_a, 0], [sin_a, cos_a, 0], [0, 0, 1]], dtype=float
        )
        base = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], dtype=float)
        transform = np.eye(4)
        transform[:3, :3] = rotate_z @ base
        transform[:3, 3] = [float(pose["x"]) - start_x, 0.0, 0.0]
        return transform

    @staticmethod
    def _average_transforms(transforms: list[np.ndarray]) -> tuple[np.ndarray, float, float]:
        translations = np.asarray([item[:3, 3] for item in transforms])
        translation = np.median(translations, axis=0)
        rotation_sum = sum((item[:3, :3] for item in transforms), np.zeros((3, 3)))
        u, _, vh = np.linalg.svd(rotation_sum)
        rotation = u @ vh
        if np.linalg.det(rotation) < 0:
            u[:, -1] *= -1
            rotation = u @ vh
        translation_rms = float(
            np.sqrt(np.mean(np.sum((translations - translation) ** 2, axis=1)))
        )
        angles = []
        for item in transforms:
            cosine = np.clip((np.trace(rotation.T @ item[:3, :3]) - 1) / 2, -1, 1)
            angles.append(math.degrees(math.acos(float(cosine))))
        result = np.eye(4)
        result[:3, :3], result[:3, 3] = rotation, translation
        return result, translation_rms, float(np.sqrt(np.mean(np.asarray(angles) ** 2)))

    def _turntable_calibration_metrics(self) -> dict:
        circumference = math.pi * float(self._config.get("turntable_diameter_mm", 200))
        return {"diameter_mm": 200.0, "mm_per_revolution": circumference}

    def _board_contract(self) -> dict:
        return {
            "board_columns": int(
                self._config.get("board_columns", BOARD_COLUMNS)
            ),
            "board_rows": int(self._config.get("board_rows", BOARD_ROWS)),
            "inner_corners": [
                int(self._config.get("board_columns", BOARD_COLUMNS)),
                int(self._config.get("board_rows", BOARD_ROWS)),
            ],
            "square_size_mm": float(
                self._config.get("square_size_mm", BOARD_SQUARE_MM)
            ),
            "centered_on_turntable": True,
            "scanner_frame": {
                "origin": "checkerboard/turntable center at calibration reference pose",
                "x": "radial, positive with commanded X",
                "y": "turntable tangent at Y=0",
                "z": "turntable rotation axis, positive upward",
            },
        }

    def _positions(self) -> dict[str, float]:
        status = self._hardware_call(
            "motor status",
            self._motor.get_motor_status,
            float(self._config.get("motion_timeout_s", 10.0)),
        )
        return {axis: float(status["positions"][axis]) for axis in ("x", "y", "z")}

    def _move_to(self, target: Mapping[str, float]) -> None:
        current = self._positions()
        limits = self._config.get("axis_limits_mm", {})
        for axis in ("x", "y", "z"):
            value = float(target[axis])
            low, high = float(limits[axis]["min"]), float(limits[axis]["max"])
            if not low <= value <= high:
                raise CalibrationError(f"axis {axis.upper()} target is outside configured limits")
            delta = value - current[axis]
            moved = True
            if abs(delta) > 1e-6:
                moved = self._hardware_call(
                    f"axis {axis.upper()} move",
                    lambda axis=axis, delta=delta: self._motor.move_motor(axis, delta),
                    float(self._config.get("motion_timeout_s", 10.0)),
                )
            if not moved:
                raise CalibrationError(f"axis {axis.upper()} rejected calibration move")
            current[axis] = value
            self._check_cancelled()

    def _capture(self, name: str) -> bytes:
        camera = self._cameras[name]
        timeout = float(self._config.get("capture_timeout_s", 5.0))
        if not getattr(camera, "is_open", False) and not self._hardware_call(
            f"camera '{name}' open", camera.open, timeout
        ):
            raise CalibrationError(f"camera '{name}' failed to open")
        frame = self._hardware_call(
            f"camera '{name}' fresh capture", camera.capture_jpeg, timeout
        )
        if not frame:
            raise CalibrationError(f"camera '{name}' returned no fresh frame")
        return frame

    def _laser(self, side: str, enabled: bool) -> None:
        method = self._gpio.laser_on if enabled else self._gpio.laser_off
        if not method(side):
            raise CalibrationError(f"failed to turn laser {side} {'on' if enabled else 'off'}")

    def _lasers_off(self) -> None:
        failures = []
        if self._gpio is not None:
            for side in ("left", "right"):
                try:
                    if not self._gpio.laser_off(side):
                        failures.append(side)
                except Exception:
                    failures.append(side)
        if failures:
            raise CalibrationError(f"failed to force lasers off: {', '.join(failures)}")

    def _safe_outputs(self) -> None:
        try:
            self._lasers_off()
        except Exception:
            pass
        try:
            self._motor.stop_motor("all")
        except Exception:
            pass

    def _sleep_interruptible(self, seconds: float) -> None:
        if self._cancel.wait(max(0.0, seconds)):
            raise CalibrationCancelled("calibration cancelled")

    def _hardware_call(
        self,
        label: str,
        operation: Callable[[], Any],
        timeout_s: float,
        *,
        check_cancel: bool = True,
    ) -> Any:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise CalibrationError(f"{label} timeout must be positive")
        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def invoke() -> None:
            try:
                outcome["value"] = operation()
            except BaseException as exc:
                outcome["error"] = exc
            finally:
                completed.set()

        threading.Thread(target=invoke, name=f"calibration-{label}", daemon=True).start()
        deadline = time.monotonic() + timeout_s
        while not completed.wait(min(0.02, max(0.0, deadline - time.monotonic()))):
            if check_cancel:
                self._check_cancelled()
            if time.monotonic() >= deadline:
                raise CalibrationError(f"{label} timed out after {timeout_s:.2f}s")
        if check_cancel:
            self._check_cancelled()
        if "error" in outcome:
            raise CalibrationError(f"{label} failed: {outcome['error']}") from outcome["error"]
        return outcome.get("value")

    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise CalibrationCancelled("calibration cancelled")

    def _set_phase(self, phase: str, step: str, progress: float) -> None:
        with self._lock:
            self._status.update(phase=phase, step=step, progress=round(float(progress), 1))

    def _set_error(self, phase: str, error: str) -> None:
        with self._lock:
            self._status.update(phase=phase, step=error, error=error)
