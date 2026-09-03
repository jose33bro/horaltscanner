"""Automatic, guarded geometric calibration for the physical scanner."""

from __future__ import annotations

import copy
import itertools
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


class CheckerboardDetectionTimeout(CalibrationError):
    """One bounded checkerboard attempt reached its deadline."""


class CheckerboardDetectionRejected(CalibrationError):
    """One checkerboard frame failed detection or framing quality checks."""


BOARD_COLUMNS = 11
BOARD_ROWS = 6
BOARD_SQUARE_MM = 13.0
CALIBRATION_MAX_X_MM = 195.0
CALIBRATION_MAX_Z_MM = 40.0
BOARD_TO_SCANNER_AT_REFERENCE = np.array(
    [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    dtype=float,
)
PNP_BOARD_FRAME_ADJUSTMENTS = {
    "identity": np.eye(3, dtype=float),
    "rotate_180_about_board_x": np.diag([1.0, -1.0, -1.0]),
    "rotate_180_about_board_y": np.diag([-1.0, 1.0, -1.0]),
    "rotate_180_about_board_normal": np.diag([-1.0, -1.0, 1.0]),
}


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


def _convex_hull_area(points: np.ndarray) -> float:
    unique = sorted({(float(point[0]), float(point[1])) for point in points})
    if len(unique) < 3:
        return 0.0

    def cross(origin: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (
            a[1] - origin[1]
        ) * (b[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    return 0.5 * abs(
        sum(
            hull[index][0] * hull[(index + 1) % len(hull)][1]
            - hull[(index + 1) % len(hull)][0] * hull[index][1]
            for index in range(len(hull))
        )
    )


def checkerboard_view_metrics(
    views: list[Mapping[str, Any]],
    *,
    duplicate_corner_rms: float = 0.002,
    board_columns: int = BOARD_COLUMNS,
) -> dict[str, Any]:
    """Measure checkerboard motion without assuming its center must translate."""
    normalized_views: list[np.ndarray] = []
    centers: list[np.ndarray] = []
    board_scales: list[float] = []
    angles: list[float] = []
    for view in views:
        corners = np.asarray(view["corners"], dtype=float).reshape(-1, 2)
        width, height = view["image_size"]
        if (
            corners.shape[0] < board_columns
            or width <= 0
            or height <= 0
            or not np.isfinite(corners).all()
        ):
            raise CalibrationError("invalid checkerboard view")
        normalized = corners / np.array([width, height], dtype=float)
        normalized_views.append(normalized)
        centers.append(normalized.mean(axis=0))
        board_scales.append(math.sqrt(max(_convex_hull_area(normalized), 0.0)))
        vector = normalized[board_columns - 1] - normalized[0]
        angles.append(math.degrees(math.atan2(float(vector[1]), float(vector[0]))))

    pairwise_motion: list[float] = []
    pairwise_shape_motion: list[float] = []
    unique: list[np.ndarray] = []
    for normalized in normalized_views:
        if not unique or all(
            float(np.sqrt(np.mean(np.sum((normalized - prior) ** 2, axis=1))))
            >= duplicate_corner_rms
            for prior in unique
        ):
            unique.append(normalized)
    for first in range(len(normalized_views)):
        for second in range(first + 1, len(normalized_views)):
            left, right = normalized_views[first], normalized_views[second]
            pairwise_motion.append(
                float(np.sqrt(np.mean(np.sum((left - right) ** 2, axis=1))))
            )
            left_shape = left - left.mean(axis=0)
            right_shape = right - right.mean(axis=0)
            pairwise_shape_motion.append(
                float(np.sqrt(np.mean(np.sum((left_shape - right_shape) ** 2, axis=1))))
            )

    center_array = np.asarray(centers, dtype=float)
    unwrapped_angles = np.degrees(np.unwrap(np.radians(angles)))
    scale_median = float(np.median(board_scales)) if board_scales else 0.0
    corner_tracks = (
        np.stack(normalized_views, axis=0).transpose(1, 0, 2)
        if normalized_views
        else np.empty((0, 0, 2))
    )
    track_hulls = [_convex_hull_area(track) for track in corner_tracks]
    return {
        "views": len(views),
        "unique_views": len(unique),
        "duplicate_corner_rms_threshold": duplicate_corner_rms,
        "center_span": (
            float(max(np.ptp(center_array[:, 0]), np.ptp(center_array[:, 1])))
            if len(center_array)
            else 0.0
        ),
        "corresponding_corner_motion_rms": max(pairwise_motion, default=0.0),
        "centered_corner_shape_motion_rms": max(pairwise_shape_motion, default=0.0),
        "relative_scale_span": (
            float(np.ptp(board_scales)) / scale_median if scale_median > 1e-12 else 0.0
        ),
        "angle_span_deg": (
            float(np.ptp(unwrapped_angles)) if len(unwrapped_angles) else 0.0
        ),
        "median_corner_track_hull": float(np.median(track_hulls)) if track_hulls else 0.0,
        "maximum_corner_track_hull": max(track_hulls, default=0.0),
    }


def validate_view_diversity(
    views: list[Mapping[str, Any]],
    *,
    minimum_views: int,
    minimum_corner_motion: float = 0.01,
    minimum_shape_motion: float = 0.004,
    minimum_relative_scale_span: float = 0.01,
    minimum_angle_span_deg: float = 2.0,
    duplicate_corner_rms: float = 0.002,
) -> dict[str, Any]:
    """Reject repeated or geometrically degenerate views before OpenCV calibration."""
    if len(views) < minimum_views:
        raise CalibrationError(f"insufficient accepted views: {len(views)} < {minimum_views}")
    metrics = checkerboard_view_metrics(
        views, duplicate_corner_rms=duplicate_corner_rms
    )
    thresholds = {
        "minimum_unique_views": minimum_views,
        "minimum_corner_motion": minimum_corner_motion,
        "minimum_shape_motion": minimum_shape_motion,
        "minimum_relative_scale_span": minimum_relative_scale_span,
        "minimum_angle_span_deg": minimum_angle_span_deg,
    }
    failures = []
    if metrics["unique_views"] < minimum_views:
        failures.append("repeated near-identical checkerboard views")
    if metrics["corresponding_corner_motion_rms"] < minimum_corner_motion:
        failures.append("insufficient corresponding-corner motion")
    if (
        metrics["centered_corner_shape_motion_rms"] < minimum_shape_motion
        and metrics["relative_scale_span"] < minimum_relative_scale_span
        and metrics["angle_span_deg"] < minimum_angle_span_deg
    ):
        failures.append("insufficient checkerboard shape/scale/orientation diversity")
    metrics["thresholds"] = thresholds
    if failures:
        summary = ", ".join(
            f"{key}={value:.5g}" if isinstance(value, float) else f"{key}={value}"
            for key, value in metrics.items()
            if key != "thresholds"
        )
        limits = ", ".join(f"{key}={value:g}" for key, value in thresholds.items())
        raise CalibrationError(
            f"{'; '.join(failures)}; diversity metrics [{summary}]; "
            f"thresholds [{limits}]"
        )
    return metrics


def extract_laser_line_pixels(
    cv: Any,
    ambient: np.ndarray,
    laser: np.ndarray,
    corners: Any,
    *,
    config: Mapping[str, Any],
) -> tuple[list[list[float]], dict[str, Any]]:
    """Extract one coherent laser ridge inside the checkerboard safe interior."""
    diagnostic: dict[str, Any] = {"accepted": False}
    if (
        ambient is None
        or laser is None
        or ambient.shape != laser.shape
        or ambient.ndim != 3
        or ambient.shape[2] < 3
    ):
        diagnostic["reason"] = "ambient and laser frames must be matching color images"
        return [], diagnostic

    columns = int(config.get("board_columns", BOARD_COLUMNS))
    rows = int(config.get("board_rows", BOARD_ROWS))
    try:
        board_corners = np.asarray(corners, dtype=float).reshape(-1, 2)
    except (TypeError, ValueError):
        diagnostic["reason"] = "checkerboard corners are missing or invalid"
        return [], diagnostic
    if (
        columns < 2
        or rows < 2
        or len(board_corners) != columns * rows
        or not np.isfinite(board_corners).all()
    ):
        diagnostic["reason"] = "checkerboard corners are missing or invalid"
        return [], diagnostic

    erode_fraction = float(config.get("laser_roi_erode_fraction", 0.06))
    row_stride = int(config.get("laser_row_stride", 2))
    delta_threshold = float(config.get("laser_delta_threshold", 35))
    excess_threshold = float(
        config.get("laser_excess_threshold", max(12.0, delta_threshold / 2.0))
    )
    minimum_rows = int(config.get("minimum_laser_line_rows", 12))
    minimum_span_fraction = float(
        config.get("minimum_laser_line_span_fraction", 0.20)
    )
    minimum_continuity = float(
        config.get("minimum_laser_line_continuity", 0.45)
    )
    maximum_residual = float(
        config.get("maximum_laser_line_residual_px", 2.0)
    )
    maximum_width = float(config.get("maximum_laser_line_width_px", 12.0))
    maximum_gap_fraction = float(
        config.get("maximum_laser_line_gap_fraction", 0.12)
    )
    if (
        not 0 < erode_fraction < 0.5
        or row_stride <= 0
        or delta_threshold <= 0
        or excess_threshold <= 0
        or minimum_rows < 2
        or not 0 < minimum_span_fraction <= 1
        or not 0 < minimum_continuity <= 1
        or maximum_residual <= 0
        or maximum_width <= 0
        or not 0 < maximum_gap_fraction <= 1
    ):
        raise CalibrationError("laser extraction thresholds are invalid")

    corner_grid = board_corners.reshape(rows, columns, 2)
    polygon = np.asarray(
        (
            corner_grid[0, 0],
            corner_grid[0, -1],
            corner_grid[-1, -1],
            corner_grid[-1, 0],
        ),
        dtype=float,
    )
    center = polygon.mean(axis=0)
    safe_polygon = center + (polygon - center) * (1.0 - erode_fraction)
    height, width = ambient.shape[:2]
    if (
        np.any(safe_polygon[:, 0] < 0)
        or np.any(safe_polygon[:, 0] >= width)
        or np.any(safe_polygon[:, 1] < 0)
        or np.any(safe_polygon[:, 1] >= height)
    ):
        diagnostic["reason"] = "checkerboard safe interior falls outside the frame"
        return [], diagnostic

    roi = np.zeros((height, width), dtype=np.uint8)
    cv.fillConvexPoly(roi, np.rint(safe_polygon).astype(np.int32), 255)
    roi_rows, roi_columns = np.where(roi > 0)
    if not len(roi_rows):
        diagnostic["reason"] = "checkerboard safe interior is empty"
        return [], diagnostic
    board_height = float(np.ptp(safe_polygon[:, 1]))

    ambient_peak = ambient[:, :, :3].max(axis=2)
    saturated = (ambient_peak >= 245).astype(np.uint8)
    saturation_radius = int(config.get("laser_ambient_saturation_radius_px", 4))
    if saturation_radius < 0:
        raise CalibrationError("laser ambient saturation radius must be non-negative")
    if saturation_radius:
        size = saturation_radius * 2 + 1
        saturated = cv.dilate(
            saturated,
            np.ones((size, size), dtype=np.uint8),
            iterations=1,
        )

    ambient_red = ambient[:, :, 2].astype(np.int16)
    laser_red = laser[:, :, 2].astype(np.int16)
    delta = laser_red - ambient_red
    excess = laser_red - np.maximum(
        laser[:, :, 1], laser[:, :, 0]
    ).astype(np.int16)
    candidate_mask = (
        (delta >= delta_threshold)
        & (excess >= excess_threshold)
        & (roi > 0)
        & (saturated == 0)
    )
    response = delta.astype(float) + 0.5 * np.maximum(excess, 0)
    diagnostic.update(
        roi_area_px=int(np.count_nonzero(roi)),
        roi_erode_fraction=erode_fraction,
        excluded_ambient_saturated_px=int(
            np.count_nonzero((saturated > 0) & (roi > 0))
        ),
        candidate_pixels=int(np.count_nonzero(candidate_mask)),
    )

    candidates: list[tuple[float, float, float, float]] = []
    maximum_peaks_per_row = int(config.get("maximum_laser_peaks_per_row", 4))
    if maximum_peaks_per_row <= 0:
        raise CalibrationError("maximum_laser_peaks_per_row must be positive")
    for row in range(int(roi_rows.min()), int(roi_rows.max()) + 1, row_stride):
        active = np.flatnonzero(candidate_mask[row])
        if not active.size:
            continue
        split_at = np.flatnonzero(np.diff(active) > 1) + 1
        runs = np.split(active, split_at)
        peaks = []
        for run in runs:
            scores = response[row, run]
            peak_index = int(np.argmax(scores))
            weights = np.maximum(scores - min(delta_threshold, excess_threshold), 1.0)
            peaks.append(
                (
                    float(np.average(run, weights=weights)),
                    float(row),
                    float(scores[peak_index]),
                    float(len(run)),
                )
            )
        candidates.extend(
            sorted(peaks, key=lambda item: item[2], reverse=True)[
                :maximum_peaks_per_row
            ]
        )

    candidate_rows = sorted({int(item[1]) for item in candidates})
    diagnostic["candidate_rows"] = len(candidate_rows)
    if len(candidate_rows) < minimum_rows:
        diagnostic["reason"] = (
            f"laser ridge has {len(candidate_rows)} candidate rows; "
            f"{minimum_rows} required"
        )
        return [], diagnostic

    values = np.asarray(candidates, dtype=float)
    row_span = float(np.ptp(values[:, 1]))
    minimum_span = max(float(row_stride * (minimum_rows - 1)), board_height * minimum_span_fraction)
    top = values[values[:, 1] <= values[:, 1].min() + row_span * 0.35]
    bottom = values[values[:, 1] >= values[:, 1].max() - row_span * 0.35]
    top = top[np.argsort(top[:, 2])[-48:]]
    bottom = bottom[np.argsort(bottom[:, 2])[-48:]]
    inlier_tolerance = max(maximum_residual * 2.0, 2.5)
    by_row: dict[int, np.ndarray] = {}
    for row in candidate_rows:
        by_row[row] = values[values[:, 1] == row]

    best: tuple[tuple[float, float, float, float], np.ndarray] | None = None
    for first in top:
        for last in bottom:
            delta_row = float(last[1] - first[1])
            if delta_row < minimum_span:
                continue
            slope = float((last[0] - first[0]) / delta_row)
            intercept = float(first[0] - slope * first[1])
            selected = []
            for row, row_values in by_row.items():
                residual = np.abs(
                    row_values[:, 0] - (slope * float(row) + intercept)
                )
                eligible = np.flatnonzero(residual <= inlier_tolerance)
                if eligible.size:
                    index = min(
                        eligible,
                        key=lambda item: (
                            float(residual[item]),
                            -float(row_values[item, 2]),
                        ),
                    )
                    selected.append(row_values[index])
            if len(selected) < minimum_rows:
                continue
            selected_values = np.asarray(selected, dtype=float)
            residuals = selected_values[:, 0] - (
                slope * selected_values[:, 1] + intercept
            )
            score = (
                float(len(selected_values)),
                float(np.ptp(selected_values[:, 1])),
                -float(np.sqrt(np.mean(residuals**2))),
                float(selected_values[:, 2].sum()),
            )
            if best is None or score > best[0]:
                best = score, selected_values

    if best is None:
        diagnostic["reason"] = "no coherent laser ridge spans the checkerboard interior"
        return [], diagnostic

    selected = best[1]
    for _ in range(2):
        coefficients = np.polyfit(selected[:, 1], selected[:, 0], 1)
        residuals = selected[:, 0] - np.polyval(coefficients, selected[:, 1])
        keep = np.abs(residuals) <= inlier_tolerance
        selected = selected[keep]
        if len(selected) < minimum_rows:
            diagnostic["reason"] = (
                f"laser ridge retains {len(selected)} rows after line fitting; "
                f"{minimum_rows} required"
            )
            return [], diagnostic

    coefficients = np.polyfit(selected[:, 1], selected[:, 0], 1)
    residuals = selected[:, 0] - np.polyval(coefficients, selected[:, 1])
    residual_rms = float(np.sqrt(np.mean(residuals**2)))
    line_rows = np.sort(selected[:, 1])
    line_span = float(np.ptp(line_rows))
    continuity = float(
        len(line_rows) * row_stride / max(line_span + row_stride, row_stride)
    )
    maximum_gap = float(np.max(np.diff(line_rows))) if len(line_rows) > 1 else math.inf
    median_width = float(np.median(selected[:, 3]))
    maximum_gap = max(maximum_gap, 0.0)
    diagnostic.update(
        line_rows=int(len(selected)),
        line_span_px=line_span,
        line_span_fraction=line_span / max(board_height, 1.0),
        line_continuity=continuity,
        maximum_row_gap_px=maximum_gap,
        line_residual_rms_px=residual_rms,
        median_line_width_px=median_width,
        line_slope_x_per_y=float(coefficients[0]),
    )
    failures = []
    if len(selected) < minimum_rows:
        failures.append(f"rows {len(selected)} < {minimum_rows}")
    if line_span < minimum_span:
        failures.append(f"span {line_span:.1f}px < {minimum_span:.1f}px")
    if continuity < minimum_continuity:
        failures.append(
            f"continuity {continuity:.3f} < {minimum_continuity:.3f}"
        )
    if maximum_gap > max(row_stride * 2.0, board_height * maximum_gap_fraction):
        failures.append("row continuity gap is too large")
    if residual_rms > maximum_residual:
        failures.append(
            f"line residual {residual_rms:.2f}px > {maximum_residual:.2f}px"
        )
    if median_width > maximum_width:
        failures.append(
            f"median line width {median_width:.1f}px > {maximum_width:.1f}px"
        )
    if failures:
        diagnostic["reason"] = "; ".join(failures)
        return [], diagnostic

    diagnostic["accepted"] = True
    diagnostic["reason"] = None
    pixels = selected[np.argsort(selected[:, 1]), :2].tolist()
    return pixels, diagnostic


def fit_plane_robust(
    points: Any,
    *,
    minimum_points: int = 20,
    return_inlier_mask: bool = False,
) -> tuple[np.ndarray, float, dict]:
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
    inlier_indexes = np.flatnonzero(radial <= radial_limit)
    inliers = values[inlier_indexes]
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
        inlier_indexes = inlier_indexes[distances <= threshold]
        inliers = selected
    center = inliers.mean(axis=0)
    _, singular_values, vh = np.linalg.svd(inliers - center, full_matrices=False)
    if (
        len(singular_values) < 2
        or singular_values[1] <= max(singular_values[0] * 1e-6, 1e-6)
    ):
        raise CalibrationError(
            "laser plane points are rank-deficient after robust rejection"
        )
    normal = vh[-1]
    normal /= np.linalg.norm(normal)
    offset = -float(np.dot(normal, center))
    residuals = inliers @ normal + offset
    rms = float(np.sqrt(np.mean(residuals ** 2)))
    quality = {
        "accepted": True,
        "rms_mm": rms,
        "inliers": int(len(inliers)),
        "samples": int(len(values)),
    }
    if return_inlier_mask:
        mask = np.zeros(len(values), dtype=bool)
        mask[inlier_indexes] = True
        quality["inlier_mask"] = mask.tolist()
    return normal, offset, quality


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
            "calibration checkerboard must be exactly 11x6 inner corners with 13mm squares"
        )

    cameras = calibration.get("cameras", {})
    for name in ("pi", "usb"):
        camera = cameras.get(name, {})
        matrix(camera.get("intrinsic_matrix"), (3, 3), f"{name} intrinsic_matrix")
        transform = matrix(camera.get("camera_to_scanner"), (4, 4), f"{name} camera_to_scanner")
        if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-6):
            raise CalibrationError(f"{name} camera_to_scanner is not homogeneous")
        rotation = transform[:3, :3]
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6) or not math.isclose(
            float(np.linalg.det(rotation)), 1.0, rel_tol=0, abs_tol=1e-6
        ):
            raise CalibrationError(
                f"{name} camera_to_scanner rotation must be right-handed and orthonormal"
            )
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
        carriage_axis = camera.get("carriage_axis")
        if carriage_axis is not None:
            if carriage_axis not in {"x", "y", "z"}:
                raise CalibrationError(f"{name} carriage axis is invalid")
            direction = np.asarray(camera.get("carriage_direction"), dtype=float)
            if (
                direction.shape != (3,)
                or not np.isfinite(direction).all()
                or np.linalg.norm(direction) <= 1e-9
            ):
                raise CalibrationError(f"{name} carriage direction is invalid")
            try:
                reference = float(camera.get("reference_axis_position_mm", math.nan))
            except (TypeError, ValueError):
                reference = math.nan
            if not math.isfinite(reference):
                raise CalibrationError(
                    f"{name} reference_axis_position_mm is required"
                )
            scale = camera.get("carriage_scale_mm_per_commanded_mm")
            if scale is not None:
                try:
                    scale = float(scale)
                except (TypeError, ValueError):
                    scale = math.nan
                if (
                    not math.isfinite(scale)
                    or scale <= 0
                    or not math.isclose(
                        scale,
                        float(np.linalg.norm(direction)),
                        rel_tol=1e-6,
                        abs_tol=1e-6,
                    )
                ):
                    raise CalibrationError(
                        f"{name} carriage scale is inconsistent with carriage direction"
                    )

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
        try:
            views = float(quality.get("views", math.nan))
            minimum_views = float(quality.get("minimum_views", math.nan))
            orientations = float(
                quality.get("independent_board_orientations", math.nan)
            )
            minimum_orientations = float(
                quality.get("minimum_board_orientations", math.nan)
            )
        except (TypeError, ValueError):
            views = minimum_views = orientations = minimum_orientations = math.nan
        if (
            plane.get("source") != "pi_checkerboard_structured_light"
            or not quality.get("accepted")
            or quality.get("primary_camera") != "pi"
            or not math.isfinite(rms)
            or not math.isfinite(maximum)
            or maximum <= 0
            or maximum > 2.0
            or rms > maximum
            or rms > 2.0
            or not all(
                math.isfinite(value)
                for value in (
                    views,
                    minimum_views,
                    orientations,
                    minimum_orientations,
                )
            )
            or minimum_views < 3
            or views < minimum_views
            or minimum_orientations < 3
            or orientations < minimum_orientations
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
    command_scale = float(turntable.get("command_radians_per_mm", math.nan))
    commanded_revolution = float(
        turntable.get("commanded_mm_per_revolution", math.nan)
    )
    if (
        not math.isfinite(command_scale)
        or abs(command_scale) <= 1e-12
        or not math.isfinite(commanded_revolution)
        or commanded_revolution <= 0
        or not math.isclose(
            commanded_revolution,
            2.0 * math.pi / abs(command_scale),
            rel_tol=1e-8,
            abs_tol=1e-6,
        )
        or turntable.get("command_direction")
        != ("positive" if command_scale > 0 else "negative")
    ):
        raise CalibrationError("turntable signed command scale is invalid")
    reference_pose = turntable.get("reference_pose_mm", {})
    if not isinstance(reference_pose, Mapping) or not all(
        math.isfinite(float(reference_pose.get(axis, math.nan)))
        for axis in ("x", "y", "z")
    ):
        raise CalibrationError("turntable reference_pose_mm is invalid")

    lidar = calibration.get("lidar", {})
    transform = matrix(lidar.get("lidar_to_scanner"), (4, 4), "TF-Luna lidar_to_scanner")
    if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-6):
        raise CalibrationError("TF-Luna transform is not homogeneous")
    if lidar.get("source") != "operator_measured_origin_direction":
        raise CalibrationError("TF-Luna transform source is not recorded")
    carriage_axis = lidar.get("carriage_axis")
    if carriage_axis is not None:
        if carriage_axis not in {"x", "y", "z"}:
            raise CalibrationError("TF-Luna carriage axis is invalid")
        direction = np.asarray(lidar.get("carriage_direction"), dtype=float)
        if (
            direction.shape != (3,)
            or not np.isfinite(direction).all()
            or np.linalg.norm(direction) <= 1e-9
        ):
            raise CalibrationError("TF-Luna carriage direction is invalid")
        try:
            reference = float(lidar.get("reference_axis_position_mm", math.nan))
        except (TypeError, ValueError):
            reference = math.nan
        if not math.isfinite(reference):
            raise CalibrationError("TF-Luna reference_axis_position_mm is required")
        scale = lidar.get("carriage_scale_mm_per_commanded_mm")
        if scale is not None:
            try:
                scale = float(scale)
            except (TypeError, ValueError):
                scale = math.nan
            if (
                not math.isfinite(scale)
                or scale <= 0
                or not math.isclose(
                    scale,
                    float(np.linalg.norm(direction)),
                    rel_tol=1e-6,
                    abs_tol=1e-6,
                )
            ):
                raise CalibrationError(
                    "TF-Luna carriage scale is inconsistent with carriage direction"
                )
        usb = cameras.get("usb", {})
        usb_direction = np.asarray(usb.get("carriage_direction"), dtype=float)
        if (
            usb.get("carriage_axis") == carriage_axis
            and usb_direction.shape == (3,)
            and not np.allclose(direction, usb_direction, rtol=1e-8, atol=1e-8)
        ):
            raise CalibrationError(
                "TF-Luna carriage direction must match the measured USB carriage fit"
            )
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
    signed = float(x_scale.get("signed_mm_per_commanded_mm", math.nan))
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
        or not math.isfinite(signed)
        or expected <= 0
        or tolerance < 0
        or maximum_repeatability <= 0
        or abs(measured - expected) > tolerance * expected
        or not math.isclose(abs(signed), measured, rel_tol=1e-8, abs_tol=1e-8)
        or x_scale.get("command_direction")
        != ("positive" if signed > 0 else "negative")
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

    def _read(self, path: Path | None = None, *, missing_ok: bool = False) -> dict:
        selected = path or self.path
        if missing_ok and not selected.exists():
            return {"schema_version": 1}
        with open(selected, encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, calibration: Mapping[str, Any], report: Mapping[str, Any]) -> None:
        validate_calibration_payload(calibration)
        current = self._read(missing_ok=True)
        updated = copy.deepcopy(current)
        updated["scan_calibration"] = copy.deepcopy(dict(calibration))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        backup_tmp = self.backup_path.with_suffix(self.backup_path.suffix + ".new")
        config_tmp = self.path.with_suffix(self.path.suffix + ".new")
        report_tmp = self.report_path.with_suffix(self.report_path.suffix + ".new")
        previous_sidecars = {
            destination: destination.read_bytes() if destination.exists() else None
            for destination in (self.backup_path, self.report_path)
        }
        installed_sidecars: list[Path] = []
        try:
            self._write_json(backup_tmp, current)
            self._write_json(config_tmp, updated)
            self._write_json(report_tmp, dict(report))
            os.replace(report_tmp, self.report_path)
            installed_sidecars.append(self.report_path)
            os.replace(backup_tmp, self.backup_path)
            installed_sidecars.append(self.backup_path)
            # The active calibration is switched only after every sidecar is durable.
            os.replace(config_tmp, self.path)
        except Exception:
            restore_errors = []
            for destination in reversed(installed_sidecars):
                previous = previous_sidecars[destination]
                try:
                    if previous is None:
                        destination.unlink()
                    else:
                        restore_tmp = destination.with_suffix(
                            destination.suffix + ".restore"
                        )
                        self._write_bytes(restore_tmp, previous)
                        os.replace(restore_tmp, destination)
                except FileNotFoundError:
                    pass
                except Exception as restore_error:
                    restore_errors.append(
                        f"{destination.name}: {restore_error}"
                    )
            if restore_errors:
                raise CalibrationError(
                    "calibration persistence failed and sidecar rollback also "
                    f"failed ({'; '.join(restore_errors)})"
                )
            raise
        finally:
            for temporary in (
                backup_tmp,
                config_tmp,
                report_tmp,
                self.backup_path.with_suffix(self.backup_path.suffix + ".restore"),
                self.report_path.with_suffix(self.report_path.suffix + ".restore"),
            ):
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
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o640)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _write_bytes(path: Path, payload: bytes) -> None:
        with open(path, "wb") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o640)
            handle.write(payload)
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
        self._lidar_output_restore_required = False
        self._status = self._new_status()
        self._report: dict[str, Any] = {}
        self._reference_pose = dict(
            self._config.get("starting_pose_mm", {"x": 195, "y": 0, "z": 20})
        )
        circumference = math.pi * float(self._config.get("turntable_diameter_mm", 200))
        self._motion_model = {
            "x_mm_per_commanded_mm": 1.0,
            "y_radians_per_commanded_mm": 2.0 * math.pi / circumference,
        }

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
            "last_checkerboard_rejection": {"pi": None, "usb": None},
            "lidar_output_suspended": False,
            "view_diversity": {},
            "pnp_views": {"pi": [], "usb": []},
            "axis_model_candidates": {},
            "laser_views": {
                side: {name: [] for name in ("pi", "usb")}
                for side in ("left", "right")
            },
        }

    def status(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._status)

    def _checkerboard_framing_thresholds(self) -> tuple[float, float]:
        minimum_margin = float(self._config.get("minimum_frame_margin", 0.02))
        minimum_coverage = float(self._config.get("minimum_board_coverage", 0.03))
        if (
            not math.isfinite(minimum_margin)
            or not 0 <= minimum_margin < 0.5
            or not math.isfinite(minimum_coverage)
            or not 0 < minimum_coverage <= 1
        ):
            raise CalibrationError(
                "checkerboard framing thresholds must specify "
                "0 <= minimum_frame_margin < 0.5 and "
                "0 < minimum_board_coverage <= 1"
            )
        return minimum_margin, minimum_coverage

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
                "board_columns=11, board_rows=6, square_size_mm=13"
            )
        try:
            self._checkerboard_framing_thresholds()
        except CalibrationError as exc:
            blockers.append(str(exc))
        try:
            configured_x_max = float(
                self._config.get("axis_limits_mm", {}).get("x", {}).get("max")
            )
            if not math.isfinite(configured_x_max) or configured_x_max > CALIBRATION_MAX_X_MM:
                blockers.append(
                    f"calibration X maximum must not exceed {CALIBRATION_MAX_X_MM:g}mm"
                )
        except (TypeError, ValueError):
            blockers.append("calibration X maximum must be finite")
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
        elif not callable(getattr(self._lidar, "set_output_enabled", None)):
            blockers.append("TF-Luna driver cannot control ranging output")
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
            calibration["x_scale_validation"] = self._validate_x_scale()
            calibration["turntable"] = self._turntable_calibration()
            calibration["laser_planes"] = self._calibrate_lasers(
                poses, calibration, views
            )
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
                "diagnostics": {
                    key: copy.deepcopy(self._status[key])
                    for key in (
                        "view_diversity",
                        "pnp_views",
                        "axis_model_candidates",
                        "laser_views",
                    )
                },
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
            self._report = self._failure_report("Calibration cancelled")
        except Exception as exc:
            self._set_error("error", str(exc))
            self._report = self._failure_report(str(exc))
        finally:
            self._safe_outputs()
            with self._lock:
                self._active = False
                self._status["active"] = False
            self._reservation.release()

    def _failure_report(self, error: str) -> dict:
        with self._lock:
            return {
                "schema_version": 1,
                "accepted": False,
                "created_at_utc": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                "error": error,
                "reference_pose_mm": copy.deepcopy(self._reference_pose),
                "metrics": copy.deepcopy(self._status["metrics"]),
                "diagnostics": {
                    key: copy.deepcopy(self._status[key])
                    for key in (
                        "view_diversity",
                        "pnp_views",
                        "axis_model_candidates",
                        "laser_views",
                    )
                },
            }

    def _trajectory(self, options: Mapping[str, Any]) -> list[dict[str, float]]:
        configured_start = self._starting_pose(options)
        offsets = self._config.get("pose_offsets_mm", [])
        if not offsets:
            offsets = [
                {"x": 0, "y": 0, "z": 0},
                {"x": -10, "y": 10.4719755, "z": 10},
                {"x": -20, "y": 20.9439510, "z": 20},
                {"x": -30, "y": 31.4159265, "z": 0},
                {"x": 0, "y": 41.8879020, "z": 20},
                {"x": -30, "y": 52.3598776, "z": 10},
                {"x": -15, "y": 62.8318531, "z": 20},
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
                if axis == "x":
                    high = min(high, CALIBRATION_MAX_X_MM)
                if axis == "z":
                    high = min(high, CALIBRATION_MAX_Z_MM)
                if not all(math.isfinite(value) for value in (target, low, high)) or not low <= target <= high:
                    raise CalibrationError(
                        f"calibration pose {axis.upper()}={target:.3f} is outside "
                        f"configured limits [{low}, {high}]"
                    )
            poses.append(pose)
        minimum_views = int(self._config.get("minimum_views", 6))
        if len(poses) < minimum_views:
            raise CalibrationError("configured calibration trajectory has insufficient poses")
        unique_x = np.unique(np.round([pose["x"] for pose in poses], 4))
        unique_y = np.unique(np.round([pose["y"] for pose in poses], 4))
        unique_z = np.unique(np.round([pose["z"] for pose in poses], 4))
        expected_y_scale = 2.0 / float(self._config.get("turntable_diameter_mm", 200))
        y_span_deg = math.degrees(float(np.ptp(unique_y)) * expected_y_scale)
        if len(unique_x) < 3 or float(np.ptp(unique_x)) < 20:
            raise CalibrationError(
                "calibration trajectory must contain at least three X positions spanning 20mm"
            )
        if len(unique_y) < 4 or y_span_deg < 30:
            raise CalibrationError(
                "calibration trajectory must contain at least four Y positions spanning 30deg"
            )
        if len(unique_z) < 3 or float(np.ptp(unique_z)) < 20:
            raise CalibrationError(
                "calibration trajectory must contain at least three Z positions spanning 20mm"
            )
        return poses

    def _starting_pose(self, options: Mapping[str, Any]) -> dict[str, float]:
        start = dict(self._config.get("starting_pose_mm", {"x": 195, "y": 0, "z": 20}))
        start.update(options.get("starting_pose_mm", {}))
        try:
            return {axis: float(start[axis]) for axis in ("x", "y", "z")}
        except (KeyError, TypeError, ValueError) as exc:
            raise CalibrationError("starting_pose_mm must contain finite X/Y/Z values") from exc

    def _capture_checkerboard_views(
        self, poses: list[dict[str, float]]
    ) -> dict[str, list[dict]]:
        self._check_cancelled()
        try:
            self._set_lidar_output_enabled(False)
            self._sleep_interruptible(
                float(self._config.get("lidar_output_settle_s", 0.05))
            )
            return self._capture_checkerboard_views_output_suspended(poses)
        finally:
            self._set_lidar_output_enabled(True)

    def _set_lidar_output_enabled(self, enabled: bool) -> None:
        setter = getattr(self._lidar, "set_output_enabled", None)
        if setter is None:
            raise CalibrationError("TF-Luna driver cannot control ranging output")
        label = f"TF-Luna output {'enable' if enabled else 'suspend'}"
        if not enabled:
            with self._lock:
                self._lidar_output_restore_required = True
                self._status["lidar_output_suspended"] = True
        timeout_s = float(self._config.get("lidar_timeout_s", 2.0))
        try:
            succeeded = setter(enabled, timeout_s=timeout_s)
        except Exception as exc:
            raise CalibrationError(f"{label} failed: {exc}") from exc
        if succeeded is not True:
            raise CalibrationError(f"{label} failed")
        if enabled:
            with self._lock:
                self._lidar_output_restore_required = False
                self._status["lidar_output_suspended"] = False

    def _capture_checkerboard_views_output_suspended(
        self, poses: list[dict[str, float]]
    ) -> dict[str, list[dict]]:
        views: dict[str, list[dict]] = {"pi": [], "usb": []}
        frames_per_pose = int(self._config.get("fresh_frames_per_pose", 3))
        pose_timeout = float(self._config.get("checkerboard_pose_timeout_s", 35.0))
        detector_timeout = float(self._config.get("checkerboard_timeout_s", 8.0))
        if (
            frames_per_pose <= 0
            or not math.isfinite(pose_timeout)
            or pose_timeout <= 0
            or not math.isfinite(detector_timeout)
            or detector_timeout <= 0
        ):
            raise CalibrationError(
                "fresh_frames_per_pose and checkerboard timeouts must be positive"
            )
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
            pose_deadline = time.monotonic() + pose_timeout
            failures: dict[str, str] = {}
            for name in ("pi", "usb"):
                candidate, timed_out, deadline_exhausted, rejection_reasons = (
                    self._capture_checkerboard_candidate(
                        name,
                        pose,
                        frames_per_pose=frames_per_pose,
                        pose_deadline=pose_deadline,
                    )
                )
                with self._lock:
                    if candidate is None:
                        self._status["rejected_views"][name] += 1
                    else:
                        views[name].append(candidate)
                        self._status["accepted_views"][name] += 1
                if candidate is None:
                    details = []
                    details.extend(rejection_reasons)
                    if timed_out:
                        details.append(f"{timed_out} detector timeout(s)")
                    if deadline_exhausted:
                        details.append(f"{pose_timeout:g}s pose deadline exhausted")
                    failures[name] = ", ".join(details) or "no exact 11x6 detection"
                with self._lock:
                    self._status["last_checkerboard_rejection"][name] = failures.get(name)
            if index == 0:
                with self._lock:
                    self._status["starting_pose_validated"] = all(views[name] for name in views)
                missing = [name for name in ("pi", "usb") if not views[name]]
                if missing:
                    raise CalibrationError(
                        "starting pose framing rejected for camera(s): "
                        + ", ".join(missing)
                        + " ("
                        + "; ".join(f"{name}: {failures[name]}" for name in missing)
                        + ")"
                        + "; no multi-pose calibration trajectory was started"
                    )
        self._check_cancelled()
        minimum = int(self._config.get("minimum_views", 6))
        for name in ("pi", "usb"):
            try:
                metrics = validate_view_diversity(
                    views[name],
                    minimum_views=minimum,
                    minimum_corner_motion=float(
                        self._config.get("minimum_corner_motion", 0.01)
                    ),
                    minimum_shape_motion=float(
                        self._config.get("minimum_shape_motion", 0.004)
                    ),
                    minimum_relative_scale_span=float(
                        self._config.get("minimum_relative_scale_span", 0.01)
                    ),
                    minimum_angle_span_deg=float(
                        self._config.get("minimum_angle_span_deg", 2.0)
                    ),
                    duplicate_corner_rms=float(
                        self._config.get("duplicate_corner_rms", 0.002)
                    ),
                )
            except CalibrationError:
                metrics = checkerboard_view_metrics(
                    views[name],
                    duplicate_corner_rms=float(
                        self._config.get("duplicate_corner_rms", 0.002)
                    ),
                )
                metrics["thresholds"] = {
                    "minimum_unique_views": minimum,
                    "minimum_corner_motion": float(
                        self._config.get("minimum_corner_motion", 0.01)
                    ),
                    "minimum_shape_motion": float(
                        self._config.get("minimum_shape_motion", 0.004)
                    ),
                    "minimum_relative_scale_span": float(
                        self._config.get("minimum_relative_scale_span", 0.01)
                    ),
                    "minimum_angle_span_deg": float(
                        self._config.get("minimum_angle_span_deg", 2.0)
                    ),
                }
                with self._lock:
                    self._status["view_diversity"][name] = metrics
                raise
            with self._lock:
                self._status["view_diversity"][name] = metrics
        return views

    def _capture_checkerboard_candidate(
        self,
        name: str,
        pose: Mapping[str, float],
        *,
        frames_per_pose: int,
        pose_deadline: float,
    ) -> tuple[dict | None, int, bool, list[str]]:
        timed_out = 0
        rejection_reasons: list[str] = []
        for _ in range(frames_per_pose):
            self._check_cancelled()
            remaining = pose_deadline - time.monotonic()
            if remaining <= 0:
                return None, timed_out, True, rejection_reasons
            try:
                frame = self._capture(
                    name,
                    timeout_s=min(
                        float(self._config.get("capture_timeout_s", 5.0)),
                        remaining,
                    ),
                )
            except CalibrationCancelled:
                raise
            except CalibrationError:
                if time.monotonic() >= pose_deadline:
                    return None, timed_out, True, rejection_reasons
                raise
            remaining = pose_deadline - time.monotonic()
            if remaining <= 0:
                return None, timed_out, True, rejection_reasons
            try:
                candidate = self._detect_checkerboard(
                    frame,
                    pose,
                    timeout_s=min(
                        float(self._config.get("checkerboard_timeout_s", 8.0)),
                        remaining,
                    ),
                )
            except CheckerboardDetectionTimeout:
                timed_out += 1
                continue
            except CheckerboardDetectionRejected as exc:
                reason = str(exc)
                if reason not in rejection_reasons:
                    rejection_reasons.append(reason)
                continue
            if candidate is not None:
                return candidate, timed_out, False, rejection_reasons
        if not rejection_reasons and not timed_out:
            rejection_reasons.append("no exact 11x6 detection")
        return None, timed_out, time.monotonic() >= pose_deadline, rejection_reasons

    def _detect_checkerboard(
        self,
        jpeg: bytes,
        pose: Mapping[str, float],
        *,
        timeout_s: float | None = None,
    ) -> dict | None:
        image = self._cv.imdecode(np.frombuffer(jpeg, np.uint8), self._cv.IMREAD_COLOR)
        if image is None:
            raise CheckerboardDetectionRejected("camera frame could not be decoded")
        pattern = (
            int(self._config.get("board_columns", BOARD_COLUMNS)),
            int(self._config.get("board_rows", BOARD_ROWS)),
        )
        detection = find_checkerboard_bounded(
            self._cv,
            image,
            (pattern,),
            max_width=int(self._config.get("checkerboard_max_width", 1280)),
            timeout_s=(
                float(timeout_s)
                if timeout_s is not None
                else float(self._config.get("checkerboard_timeout_s", 8.0))
            ),
            allow_ir_glare_fallback=bool(
                self._config.get("checkerboard_ir_glare_fallback", True)
            ),
            cancel_event=self._cancel,
        )
        if detection.get("cancelled"):
            self._check_cancelled()
        if detection.get("timed_out"):
            raise CheckerboardDetectionTimeout("checkerboard detection timed out")
        if not detection.get("found"):
            raise CheckerboardDetectionRejected(
                str(detection.get("error") or "no exact 11x6 checkerboard detected")
            )
        if tuple(detection.get("pattern", ())) != pattern:
            detected = tuple(detection.get("pattern", ()))
            raise CheckerboardDetectionRejected(
                f"detected checkerboard pattern {detected!r}, expected {pattern!r}"
            )
        corners = np.asarray(detection["corners"], dtype=np.float32).reshape(-1, 2)
        expected_corners = pattern[0] * pattern[1]
        if len(corners) != expected_corners or not np.isfinite(corners).all():
            raise CheckerboardDetectionRejected(
                f"detector returned {len(corners)} invalid corner(s), "
                f"expected {expected_corners}"
            )
        height, width = image.shape[:2]
        minimum_margin, minimum_coverage = self._checkerboard_framing_thresholds()
        margins = {
            "left": float(corners[:, 0].min() / width),
            "right": float((width - corners[:, 0].max()) / width),
            "top": float(corners[:, 1].min() / height),
            "bottom": float((height - corners[:, 1].max()) / height),
        }
        span = np.ptp(corners, axis=0)
        coverage = float(span[0] * span[1] / (width * height))
        minimum_observed_margin = min(margins.values())
        rejection_reasons = []
        if minimum_observed_margin < minimum_margin:
            edge = min(margins, key=margins.get)
            rejection_reasons.append(
                f"{edge} corner margin {minimum_observed_margin:.4f} is below "
                f"minimum_frame_margin {minimum_margin:.4f}"
            )
        if coverage < minimum_coverage:
            rejection_reasons.append(
                f"board coverage {coverage:.4f} is below "
                f"minimum_board_coverage {minimum_coverage:.4f}"
            )
        if rejection_reasons:
            rejection_reasons.append(
                "margins "
                + ", ".join(f"{edge}={value:.4f}" for edge, value in margins.items())
            )
            raise CheckerboardDetectionRejected("; ".join(rejection_reasons))
        return {
            "corners": corners,
            "image_size": (width, height),
            "pose": dict(pose),
            "coverage": coverage,
            "frame_margins": margins,
            "minimum_frame_margin": minimum_observed_margin,
            "jpeg": jpeg,
            "detection_method": detection.get("method"),
            "glare_masked": bool(detection.get("glare_masked")),
        }

    def _solve_cameras(self, views: Mapping[str, list[dict]], options: Mapping[str, Any]) -> dict:
        calibration: dict[str, Any] = {"cameras": {}}
        self._set_phase("intrinsics", "Solving camera intrinsics and distortion", 40)
        for name in ("pi", "usb"):
            camera = self._calibrate_camera_intrinsics(views[name])
            self._solve_pnp_views(name, views[name], camera)
            calibration["cameras"][name] = camera
        self._motion_model = self._estimate_motion_model(views)
        with self._lock:
            self._status["metrics"]["axis_model"] = copy.deepcopy(self._motion_model)
        for name in ("pi", "usb"):
            camera = calibration["cameras"][name]
            step = (
                "Solving fixed Pi reference camera scanner transform"
                if name == "pi"
                else "Cross-validating moving USB camera in the scanner frame"
            )
            self._set_phase("extrinsics", step, 50)
            camera.update(self._calibrate_camera_extrinsics(name, views[name], camera, options))
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
            "pattern": "11x6_inner_corners",
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

    def _solve_pnp_views(
        self,
        name: str,
        views: list[dict],
        camera: Mapping[str, Any],
    ) -> None:
        intrinsic = np.asarray(camera["intrinsic_matrix"], dtype=float)
        distortion = np.asarray(camera["distortion_coefficients"], dtype=float)
        board_points = checkerboard_points(
            int(self._config.get("board_columns", BOARD_COLUMNS)),
            int(self._config.get("board_rows", BOARD_ROWS)),
            float(self._config.get("square_size_mm", BOARD_SQUARE_MM)),
        )
        diagnostics = []
        valid = 0
        for index, view in enumerate(views):
            ok, rvec, tvec = self._cv.solvePnP(
                board_points,
                view["corners"].reshape(-1, 1, 2),
                intrinsic,
                distortion,
            )
            if not ok:
                diagnostics.append(
                    {"view": index + 1, "pose": dict(view["pose"]), "pnp_valid": False}
                )
                continue
            rotation, _ = self._cv.Rodrigues(rvec)
            board_to_camera = np.eye(4)
            board_to_camera[:3, :3] = rotation
            board_to_camera[:3, 3] = np.asarray(tvec, dtype=float).reshape(3)
            view["rvec"], view["tvec"] = rvec, tvec
            view["board_to_camera"] = board_to_camera
            diagnostics.append(
                {
                    "view": index + 1,
                    "pose": dict(view["pose"]),
                    "pnp_valid": True,
                    "board_center_camera_mm": np.round(
                        board_to_camera[:3, 3], 4
                    ).tolist(),
                    "rotation_vector_deg": np.round(
                        np.degrees(np.asarray(rvec, dtype=float).reshape(3)), 4
                    ).tolist(),
                }
            )
            valid += 1
        with self._lock:
            self._status["pnp_views"][name] = diagnostics
        minimum = int(self._config.get("minimum_views", 6))
        if valid < minimum:
            raise CalibrationError(
                f"{name} extrinsics have insufficient valid PnP views: {valid} < {minimum}"
            )

    @staticmethod
    def _rotation_z(angle: float) -> np.ndarray:
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        return np.array(
            [[cos_a, -sin_a, 0.0], [sin_a, cos_a, 0.0], [0.0, 0.0, 1.0]],
            dtype=float,
        )

    @staticmethod
    def _rotation_residual_deg(reference: np.ndarray, observed: np.ndarray) -> float:
        cosine = np.clip((np.trace(reference.T @ observed) - 1.0) / 2.0, -1.0, 1.0)
        return math.degrees(math.acos(float(cosine)))

    @staticmethod
    def _robust_rms(
        residuals: list[float],
        *,
        minimum_cutoff: float,
    ) -> tuple[float, np.ndarray, float]:
        values = np.asarray(residuals, dtype=float)
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        cutoff = max(minimum_cutoff, median + 3.5 * 1.4826 * mad)
        mask = values <= cutoff
        if not bool(mask.any()):
            return math.inf, mask, cutoff
        return float(np.sqrt(np.mean(values[mask] ** 2))), mask, cutoff

    def _rotation_fit(self, views: Mapping[str, list[dict]], y_scale: float) -> dict:
        residuals: list[float] = []
        per_camera: dict[str, float] = {}
        for name, camera_views in views.items():
            rotations = []
            for view in camera_views:
                board_to_camera = view.get("board_to_camera")
                if board_to_camera is None:
                    continue
                angle = y_scale * (
                    float(view["pose"]["y"]) - float(self._reference_pose["y"])
                )
                rotations.append(
                    self._rotation_z(angle)
                    @ BOARD_TO_SCANNER_AT_REFERENCE
                    @ np.asarray(board_to_camera, dtype=float)[:3, :3].T
                )
            transforms = []
            for rotation in rotations:
                transform = np.eye(4)
                transform[:3, :3] = rotation
                transforms.append(transform)
            average, _, _, robust_details = self._robust_average_transforms(
                transforms
            )
            camera_residuals = [
                self._rotation_residual_deg(average[:3, :3], rotation)
                for rotation in rotations
            ]
            camera_inliers = np.asarray(
                [detail["inlier"] for detail in robust_details], dtype=bool
            )
            camera_rms = float(
                np.sqrt(
                    np.mean(np.square(np.asarray(camera_residuals)[camera_inliers]))
                )
            )
            per_camera[name] = camera_rms
            residuals.extend(
                residual
                for residual, keep in zip(camera_residuals, camera_inliers)
                if keep
            )
        rms, mask, cutoff = self._robust_rms(residuals, minimum_cutoff=0.05)
        return {
            "signed_radians_per_commanded_mm": float(y_scale),
            "rotation_rms_deg": rms,
            "per_camera_rotation_rms_deg": per_camera,
            "inliers": int(mask.sum()),
            "samples": len(residuals),
            "outlier_cutoff_deg": cutoff,
        }

    def _best_y_candidate(
        self,
        views: Mapping[str, list[dict]],
        sign: float,
        expected_scale: float,
        tolerance: float,
    ) -> dict:
        low = sign * expected_scale * (1.0 - tolerance)
        high = sign * expected_scale * (1.0 + tolerance)
        low, high = min(low, high), max(low, high)
        best: dict | None = None
        for _ in range(3):
            scales = np.linspace(low, high, 121)
            candidates = [self._rotation_fit(views, float(scale)) for scale in scales]
            index = min(
                range(len(candidates)),
                key=lambda item: candidates[item]["rotation_rms_deg"],
            )
            best = candidates[index]
            step = float(scales[1] - scales[0])
            previous_low, previous_high = low, high
            low = max(previous_low, float(scales[index]) - step)
            high = min(previous_high, float(scales[index]) + step)
        assert best is not None
        return best

    def _board_transform(
        self,
        pose: Mapping[str, float],
        *,
        x_scale: float,
        y_scale: float,
    ) -> np.ndarray:
        angle = y_scale * (
            float(pose["y"]) - float(self._reference_pose["y"])
        )
        transform = np.eye(4)
        transform[:3, :3] = (
            self._rotation_z(angle) @ BOARD_TO_SCANNER_AT_REFERENCE
        )
        transform[:3, 3] = [
            x_scale * (float(pose["x"]) - float(self._reference_pose["x"])),
            0.0,
            0.0,
        ]
        return transform

    def _reference_camera_candidates(
        self,
        views: Mapping[str, list[dict]],
        *,
        x_scale: float,
        y_scale: float,
    ) -> dict[str, list[np.ndarray]]:
        result: dict[str, list[np.ndarray]] = {}
        for name, camera_views in views.items():
            candidates = []
            for view in camera_views:
                board_to_camera = view.get("board_to_camera")
                if board_to_camera is None:
                    continue
                candidate = self._board_transform(
                    view["pose"], x_scale=x_scale, y_scale=y_scale
                ) @ np.linalg.inv(np.asarray(board_to_camera, dtype=float))
                if name == "usb":
                    candidate[:3, 3] -= np.array(
                        [
                            0.0,
                            0.0,
                            float(view["pose"]["z"])
                            - float(self._reference_pose["z"]),
                        ]
                    )
                candidates.append(candidate)
            result[name] = candidates
        return result

    def _translation_fit_score(
        self,
        views: Mapping[str, list[dict]],
        *,
        x_scale: float,
        y_scale: float,
    ) -> dict:
        by_camera = self._reference_camera_candidates(
            views, x_scale=x_scale, y_scale=y_scale
        )
        residuals: list[float] = []
        per_camera: dict[str, float] = {}
        for name, candidates in by_camera.items():
            translations = np.asarray([candidate[:3, 3] for candidate in candidates])
            center = np.median(translations, axis=0)
            camera_residuals = np.linalg.norm(translations - center, axis=1).tolist()
            camera_rms, _, _ = self._robust_rms(
                camera_residuals, minimum_cutoff=0.1
            )
            per_camera[name] = camera_rms
            residuals.extend(camera_residuals)
        rms, mask, cutoff = self._robust_rms(residuals, minimum_cutoff=0.1)
        return {
            "signed_mm_per_commanded_mm": float(x_scale),
            "translation_rms_mm": rms,
            "per_camera_translation_rms_mm": per_camera,
            "inliers": int(mask.sum()),
            "samples": len(residuals),
            "outlier_cutoff_mm": cutoff,
        }

    def _fit_x_scale(
        self,
        views: Mapping[str, list[dict]],
        *,
        y_scale: float,
    ) -> tuple[float, dict[str, dict]]:
        zero_candidates = self._reference_camera_candidates(
            views, x_scale=0.0, y_scale=y_scale
        )
        centered_x: list[float] = []
        pairwise_slopes: list[float] = []
        for name, camera_views in views.items():
            valid_views = [
                view for view in camera_views if view.get("board_to_camera") is not None
            ]
            commanded = np.asarray(
                [
                    float(view["pose"]["x"]) - float(self._reference_pose["x"])
                    for view in valid_views
                ],
                dtype=float,
            )
            candidate_x = np.asarray(
                [candidate[:3, 3][0] for candidate in zero_candidates[name]],
                dtype=float,
            )
            centered_x.extend((commanded - commanded.mean()).tolist())
            for first in range(len(commanded)):
                for second in range(first + 1, len(commanded)):
                    delta = commanded[second] - commanded[first]
                    if abs(float(delta)) > 1e-9:
                        pairwise_slopes.append(
                            float(
                                (candidate_x[second] - candidate_x[first]) / delta
                            )
                        )
        x_values = np.asarray(centered_x)
        denominator = float(np.dot(x_values, x_values))
        if denominator <= 1e-9 or not pairwise_slopes:
            raise CalibrationError("X command scale is not observable from the trajectory")
        slope = float(np.median(pairwise_slopes))
        fitted = -slope
        magnitude = abs(fitted)
        candidates = {
            "positive": self._translation_fit_score(
                views, x_scale=magnitude, y_scale=y_scale
            ),
            "negative": self._translation_fit_score(
                views, x_scale=-magnitude, y_scale=y_scale
            ),
        }
        return fitted, candidates

    def _estimate_motion_model(self, views: Mapping[str, list[dict]]) -> dict:
        reference_camera = "pi"
        reference_views = views.get(reference_camera)
        if reference_views is None:
            raise CalibrationError(
                "fixed Pi reference camera views are required to determine command signs"
            )
        sign_views = {reference_camera: reference_views}
        diameter = float(self._config.get("turntable_diameter_mm", 200.0))
        expected_y_scale = 2.0 / diameter
        y_tolerance = float(
            self._config.get("y_angular_scale_tolerance_fraction", 0.08)
        )
        y_candidates = {
            "positive": self._best_y_candidate(
                sign_views, 1.0, expected_y_scale, y_tolerance
            ),
            "negative": self._best_y_candidate(
                sign_views, -1.0, expected_y_scale, y_tolerance
            ),
        }
        selected_y_name = min(
            y_candidates,
            key=lambda name: y_candidates[name]["rotation_rms_deg"],
        )
        other_y_name = "negative" if selected_y_name == "positive" else "positive"
        selected_y = y_candidates[selected_y_name]
        y_ratio = (
            y_candidates[other_y_name]["rotation_rms_deg"] + 0.05
        ) / (selected_y["rotation_rms_deg"] + 0.05)
        minimum_ratio = float(
            self._config.get("minimum_axis_direction_score_ratio", 2.0)
        )
        maximum_rotation = float(
            self._config.get("maximum_axis_fit_rotation_rms_deg", 2.0)
        )
        y_scale = float(selected_y["signed_radians_per_commanded_mm"])
        fitted_x, x_candidates = self._fit_x_scale(sign_views, y_scale=y_scale)
        selected_x_name = "positive" if fitted_x >= 0 else "negative"
        other_x_name = "negative" if selected_x_name == "positive" else "positive"
        x_ratio = (
            x_candidates[other_x_name]["translation_rms_mm"] + 0.1
        ) / (x_candidates[selected_x_name]["translation_rms_mm"] + 0.1)
        x_tolerance = float(self._config.get("x_scale_tolerance_fraction", 0.05))
        maximum_translation = float(
            self._config.get("maximum_x_repeatability_mm", 3.0)
        )
        diagnostics = {
            "command_sign_reference_camera": reference_camera,
            "reference_camera_role": "fixed_primary_observable",
            "usb_camera_role": "moving_cross_validation_after_z_correction",
            "y": {
                "selected": selected_y_name,
                "direction_score_ratio": y_ratio,
                "minimum_direction_score_ratio": minimum_ratio,
                "candidates": y_candidates,
            },
            "x": {
                "selected": selected_x_name,
                "direction_score_ratio": x_ratio,
                "minimum_direction_score_ratio": minimum_ratio,
                "candidates": x_candidates,
            },
        }
        with self._lock:
            self._status["axis_model_candidates"] = copy.deepcopy(diagnostics)
        failures = []
        if selected_y["rotation_rms_deg"] > maximum_rotation:
            failures.append(
                f"Y angular fit RMS {selected_y['rotation_rms_deg']:.3f}deg "
                f"exceeds {maximum_rotation:.3f}deg"
            )
        relative_y_scale_error = abs(abs(y_scale) / expected_y_scale - 1.0)
        if relative_y_scale_error >= y_tolerance * 0.995:
            failures.append(
                f"Y angular scale {y_scale:.7f}rad/mm reached the "
                f"{y_tolerance:.1%} validation boundary"
            )
        if y_ratio < minimum_ratio:
            failures.append(
                "Y rotation direction from fixed Pi reference camera is ambiguous "
                f"(candidate score ratio {y_ratio:.2f})"
            )
        if abs(abs(fitted_x) - 1.0) > x_tolerance:
            failures.append(
                f"X signed scale {fitted_x:.5f}mm/mm is outside "
                f"{x_tolerance:.1%} magnitude tolerance"
            )
        selected_x = x_candidates[selected_x_name]
        if selected_x["translation_rms_mm"] > maximum_translation:
            failures.append(
                f"X fit RMS {selected_x['translation_rms_mm']:.3f}mm "
                f"exceeds {maximum_translation:.3f}mm"
            )
        if x_ratio < minimum_ratio:
            failures.append(
                "X translation direction from fixed Pi reference camera is ambiguous "
                f"(candidate score ratio {x_ratio:.2f})"
            )
        if failures:
            raise CalibrationError(
                "; ".join(failures)
                + "; axis candidates "
                + json.dumps(diagnostics, separators=(",", ":"), sort_keys=True)
            )
        return {
            "accepted": True,
            "reference_pose_mm": {
                axis: float(self._reference_pose[axis]) for axis in ("x", "y", "z")
            },
            "x_mm_per_commanded_mm": fitted_x,
            "x_direction": selected_x_name,
            "x_scale_magnitude": abs(fitted_x),
            "x_translation_rms_mm": selected_x["translation_rms_mm"],
            "y_radians_per_commanded_mm": y_scale,
            "y_direction": selected_y_name,
            "y_commanded_mm_per_revolution": 2.0 * math.pi / abs(y_scale),
            "y_rotation_rms_deg": selected_y["rotation_rms_deg"],
            "expected_y_radians_per_commanded_mm": expected_y_scale,
            "y_angular_scale_tolerance_fraction": y_tolerance,
            "minimum_direction_score_ratio": minimum_ratio,
            "command_sign_reference_camera": reference_camera,
            "candidate_residuals": diagnostics,
            "frame_convention": (
                "reference board +X -> scanner +Y, board +Y -> scanner +Z, "
                "board normal -> scanner +X; signed X and Y command directions "
                "are estimated from the fixed Pi camera PnP observations"
            ),
        }

    def _calibrate_camera_extrinsics(
        self,
        name: str,
        views: list[dict],
        camera: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> dict:
        minimum = int(self._config.get("minimum_views", 6))
        max_translation = float(self._config.get("maximum_extrinsic_rms_mm", 5.0))
        max_rotation = float(self._config.get("maximum_extrinsic_rms_deg", 3.0))
        adjustments = (
            {"identity": PNP_BOARD_FRAME_ADJUSTMENTS["identity"]}
            if name == "pi"
            else PNP_BOARD_FRAME_ADJUSTMENTS
        )
        fits: dict[str, dict[str, Any]] = {}
        for adjustment_name, adjustment in adjustments.items():
            if not math.isclose(
                float(np.linalg.det(adjustment)), 1.0, rel_tol=0, abs_tol=1e-9
            ):
                raise CalibrationError(
                    f"{name} PnP board-frame adjustment would reflect handedness"
                )
            raw_candidates = []
            candidate_views = []
            for view in views:
                board_to_camera = view.get("board_to_camera")
                if board_to_camera is None:
                    continue
                observed = np.asarray(board_to_camera, dtype=float).copy()
                if observed.shape != (4, 4) or not np.isfinite(observed).all():
                    raise CalibrationError(
                        f"{name} PnP transform must be finite, rigid, and right-handed"
                    )
                observed_rotation = observed[:3, :3]
                if (
                    not np.allclose(
                        observed_rotation.T @ observed_rotation, np.eye(3), atol=1e-5
                    )
                    or not math.isclose(
                        float(np.linalg.det(observed_rotation)),
                        1.0,
                        rel_tol=0,
                        abs_tol=1e-5,
                    )
                ):
                    raise CalibrationError(
                        f"{name} PnP transform must be finite, rigid, and right-handed"
                    )
                # All candidates rotate around the centered board origin; translations
                # are unchanged, and reflections are forbidden above.
                observed[:3, :3] = observed_rotation @ adjustment
                scanner_from_board = self._board_to_scanner(view["pose"])
                candidate = scanner_from_board @ np.linalg.inv(observed)
                raw_candidates.append(candidate)
                candidate_views.append(view)
            if len(raw_candidates) < minimum:
                raise CalibrationError(
                    f"{name} extrinsics have insufficient valid PnP views"
                )
            carriage_fit = None
            candidates = [candidate.copy() for candidate in raw_candidates]
            if name == "usb":
                try:
                    carriage_fit = self._fit_usb_carriage(
                        candidate_views,
                        raw_candidates,
                        minimum=minimum,
                    )
                except CalibrationError as exc:
                    fits[adjustment_name] = {
                        "translation_rms_mm": 1.0e12,
                        "rotation_rms_deg": 1.0e12,
                        "candidate_residuals": [],
                        "robust_pnp_inliers": 0,
                        "translation_slopes_mm_per_commanded_mm": {
                            "observable": False,
                            "error": str(exc),
                        },
                        "carriage_fit": {
                            "accepted": False,
                            "error": str(exc),
                        },
                        "accepted": False,
                        "score": 1.0e12,
                    }
                    continue
                carriage_vector = np.asarray(
                    carriage_fit["vector_mm_per_commanded_mm"], dtype=float
                )
                for candidate, view in zip(candidates, candidate_views):
                    delta_z = float(view["pose"]["z"]) - float(
                        self._reference_pose["z"]
                    )
                    candidate[:3, 3] -= carriage_vector * delta_z
            (
                transform,
                translation_rms,
                rotation_rms,
                candidate_residuals,
            ) = self._robust_average_transforms(candidates)
            inliers = sum(item["inlier"] for item in candidate_residuals)
            if name == "usb" and carriage_fit is not None:
                combined_inliers = np.asarray(
                    [
                        regression_inlier and residual["inlier"]
                        for regression_inlier, residual in zip(
                            carriage_fit["inlier_mask"], candidate_residuals
                        )
                    ],
                    dtype=bool,
                )
                if int(combined_inliers.sum()) >= max(minimum, 4):
                    try:
                        refit = self._fit_usb_carriage(
                            candidate_views,
                            raw_candidates,
                            minimum=minimum,
                            eligible=combined_inliers,
                        )
                    except CalibrationError as exc:
                        carriage_fit["accepted"] = False
                        carriage_fit["refit_error"] = str(exc)
                    else:
                        carriage_fit = refit
                        carriage_vector = np.asarray(
                            carriage_fit["vector_mm_per_commanded_mm"], dtype=float
                        )
                        candidates = [
                            candidate.copy() for candidate in raw_candidates
                        ]
                        for candidate, view in zip(candidates, candidate_views):
                            delta_z = float(view["pose"]["z"]) - float(
                                self._reference_pose["z"]
                            )
                            candidate[:3, 3] -= carriage_vector * delta_z
                        (
                            transform,
                            translation_rms,
                            rotation_rms,
                            candidate_residuals,
                        ) = self._robust_average_transforms(candidates)
                        inliers = sum(
                            item["inlier"] for item in candidate_residuals
                        )
            translation_slopes = self._translation_slope_diagnostics(
                candidate_views,
                candidates,
                np.asarray(
                    [item["inlier"] for item in candidate_residuals], dtype=bool
                ),
            )
            carriage_accepted = bool(
                carriage_fit is None or carriage_fit["accepted"]
            )
            score = (
                translation_rms / max_translation
                + rotation_rms / max_rotation
                + max(0, minimum - inliers)
            )
            if carriage_fit is not None:
                score += (
                    abs(float(carriage_fit["scale_mm_per_commanded_mm"]) - 1.0)
                    / float(carriage_fit["scale_tolerance_fraction"])
                    + float(carriage_fit["vertical_alignment_deg"])
                    / float(carriage_fit["maximum_vertical_alignment_deg"])
                    + min(
                        float(carriage_fit["design_condition_number"])
                        / float(carriage_fit["maximum_design_condition_number"]),
                        10.0,
                    )
                )
                if not carriage_accepted:
                    score += 100.0
            fits[adjustment_name] = {
                "transform": transform,
                "translation_rms_mm": translation_rms,
                "rotation_rms_deg": rotation_rms,
                "candidate_residuals": candidate_residuals,
                "robust_pnp_inliers": inliers,
                "translation_slopes_mm_per_commanded_mm": translation_slopes,
                "carriage_fit": carriage_fit,
                "accepted": (
                    inliers >= minimum
                    and translation_rms <= max_translation
                    and rotation_rms <= max_rotation
                    and carriage_accepted
                ),
                "score": score,
            }
        accepted_fits = [
            adjustment_name
            for adjustment_name, fit in fits.items()
            if fit["accepted"]
        ]
        fit_diagnostics = self._extrinsic_fit_diagnostics(fits)
        with self._lock:
            self._status["metrics"][name] = {
                **copy.deepcopy(camera["quality"]),
                "command_sign_reference_camera": "pi",
                "pnp_board_frame_candidate_fits": copy.deepcopy(fit_diagnostics),
            }
        if len(accepted_fits) > 1:
            raise CalibrationError(
                f"{name} PnP board-frame convention is ambiguous; candidates "
                + json.dumps(
                    fit_diagnostics,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        evaluable_fits = [
            adjustment_name
            for adjustment_name, fit in fits.items()
            if "transform" in fit
        ]
        if not evaluable_fits:
            raise CalibrationError(
                f"{name} PnP board-frame candidates could not be evaluated; candidates "
                + json.dumps(
                    fit_diagnostics,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        selected_adjustment = min(
            accepted_fits or evaluable_fits,
            key=lambda adjustment_name: fits[adjustment_name]["score"],
        )
        selected_fit = fits[selected_adjustment]
        transform = selected_fit["transform"]
        translation_rms = float(selected_fit["translation_rms_mm"])
        rotation_rms = float(selected_fit["rotation_rms_deg"])
        candidate_residuals = selected_fit["candidate_residuals"]
        with self._lock:
            residual_index = 0
            for diagnostic in self._status["pnp_views"][name]:
                if diagnostic.get("pnp_valid"):
                    diagnostic["extrinsic_candidate"] = copy.deepcopy(
                        candidate_residuals[residual_index]
                    )
                    residual_index += 1
        inliers = int(selected_fit["robust_pnp_inliers"])
        if inliers < minimum:
            raise CalibrationError(
                f"{name} extrinsics retain only {inliers} robust PnP inliers; "
                f"{minimum} required; residuals "
                + json.dumps(candidate_residuals, separators=(",", ":"))
            )
        if translation_rms > max_translation or rotation_rms > max_rotation:
            with self._lock:
                self._status["metrics"][name] = {
                    **copy.deepcopy(camera["quality"]),
                    "extrinsic_translation_rms_mm": translation_rms,
                    "extrinsic_rotation_rms_deg": rotation_rms,
                    "candidate_residuals": copy.deepcopy(
                        self._status["axis_model_candidates"]
                    ),
                    "pnp_board_frame_candidate_fits": copy.deepcopy(
                        fit_diagnostics
                    ),
                }
            raise CalibrationError(
                f"{name} extrinsic residual too high: {translation_rms:.2f}mm, "
                f"{rotation_rms:.2f}deg; commanded poses and PnP summaries are "
                "available in status.pnp_views; axis candidates are available in "
                "status.axis_model_candidates; PnP board-frame candidates "
                + json.dumps(
                    fit_diagnostics,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        if name == "usb" and not selected_fit["carriage_fit"]["accepted"]:
            raise CalibrationError(
                "usb carriage Z fit is outside scale, vertical alignment, or "
                "observability limits; PnP board-frame candidates "
                + json.dumps(
                    fit_diagnostics,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        quality = dict(camera["quality"])
        quality.update(
            extrinsic_translation_rms_mm=translation_rms,
            extrinsic_rotation_rms_deg=rotation_rms,
            maximum_extrinsic_rms_mm=max_translation,
            maximum_extrinsic_rms_deg=max_rotation,
            frame="turntable_center_x-radial_y-tangential_z-up",
            robust_pnp_inliers=inliers,
            pnp_candidate_residuals=candidate_residuals,
            command_sign_reference_camera="pi",
            calibration_role=(
                "fixed_primary_observable"
                if name == "pi"
                else "moving_cross_validation_after_z_correction"
            ),
            pnp_board_frame_adjustment=selected_adjustment,
            pnp_board_frame_adjustment_matrix=PNP_BOARD_FRAME_ADJUSTMENTS[
                selected_adjustment
            ].tolist(),
            pnp_board_frame_candidate_fits=fit_diagnostics,
            translation_slopes_mm_per_commanded_mm=selected_fit[
                "translation_slopes_mm_per_commanded_mm"
            ],
        )
        result = {"camera_to_scanner": transform.tolist(), "quality": quality}
        if name == "usb":
            carriage_fit = selected_fit["carriage_fit"]
            quality["carriage_fit"] = copy.deepcopy(
                {
                    key: value
                    for key, value in carriage_fit.items()
                    if key != "inlier_mask"
                }
            )
            result.update(
                carriage_axis="z",
                carriage_direction=copy.deepcopy(
                    carriage_fit["vector_mm_per_commanded_mm"]
                ),
                carriage_scale_mm_per_commanded_mm=float(
                    carriage_fit["scale_mm_per_commanded_mm"]
                ),
                reference_axis_position_mm=float(self._reference_pose["z"]),
            )
        return result

    def _fit_usb_carriage(
        self,
        views: list[dict],
        candidates: list[np.ndarray],
        *,
        minimum: int,
        eligible: np.ndarray | None = None,
    ) -> dict[str, Any]:
        regression = self._robust_translation_regression(
            views,
            candidates,
            minimum=4,
            eligible=eligible,
        )
        vector = np.asarray(regression["coefficients"][3], dtype=float)
        scale = float(np.linalg.norm(vector))
        vertical_alignment = (
            math.degrees(
                math.acos(np.clip(abs(float(vector[2])) / scale, 0.0, 1.0))
            )
            if scale > 1e-12
            else math.inf
        )
        scale_tolerance = float(
            self._config.get("usb_z_scale_tolerance_fraction", 0.15)
        )
        maximum_vertical_alignment = float(
            self._config.get("maximum_usb_z_vertical_alignment_deg", 12.0)
        )
        maximum_condition = float(
            self._config.get("maximum_carriage_fit_condition_number", 50.0)
        )
        if not all(
            math.isfinite(value) and value > 0
            for value in (
                scale_tolerance,
                maximum_vertical_alignment,
                maximum_condition,
            )
        ):
            raise CalibrationError(
                "USB carriage fit tolerances must be finite and positive"
            )
        accepted = (
            regression["observable"]
            and int(regression["inlier_mask"].sum()) >= minimum
            and abs(scale - 1.0) <= scale_tolerance
            and vertical_alignment <= maximum_vertical_alignment
            and regression["design_condition_number"] <= maximum_condition
        )
        return {
            "accepted": bool(accepted),
            "vector_mm_per_commanded_mm": vector.tolist(),
            "scale_mm_per_commanded_mm": scale,
            "signed_vertical_scale_mm_per_commanded_mm": float(vector[2]),
            "vertical_alignment_deg": vertical_alignment,
            "maximum_vertical_alignment_deg": maximum_vertical_alignment,
            "scale_tolerance_fraction": scale_tolerance,
            "design_condition_number": regression["design_condition_number"],
            "maximum_design_condition_number": maximum_condition,
            "regression_inliers": int(regression["inlier_mask"].sum()),
            "regression_samples": len(views),
            "inlier_mask": regression["inlier_mask"].tolist(),
        }

    def _robust_translation_regression(
        self,
        views: list[dict],
        candidates: list[np.ndarray],
        *,
        minimum: int,
        eligible: np.ndarray | None = None,
    ) -> dict[str, Any]:
        if len(views) != len(candidates):
            raise CalibrationError("translation regression views and candidates differ")
        deltas = np.asarray(
            [
                [
                    float(view["pose"][axis]) - float(self._reference_pose[axis])
                    for axis in ("x", "y", "z")
                ]
                for view in views
            ],
            dtype=float,
        )
        design = np.column_stack((np.ones(len(deltas)), deltas))
        translations = np.asarray(
            [candidate[:3, 3] for candidate in candidates], dtype=float
        )
        allowed = (
            np.ones(len(views), dtype=bool)
            if eligible is None
            else np.asarray(eligible, dtype=bool)
        )
        allowed_indexes = np.flatnonzero(allowed)
        if len(allowed_indexes) < minimum:
            raise CalibrationError(
                "USB carriage motion is not observable from enough PnP views"
            )

        best_coefficients = None
        best_score = math.inf
        subset_size = 4
        subsets = itertools.combinations(allowed_indexes.tolist(), subset_size)
        for subset in subsets:
            subset_indexes = np.asarray(subset, dtype=int)
            subset_design = design[subset_indexes]
            if np.linalg.matrix_rank(subset_design) < 4:
                continue
            coefficients, _, _, _ = np.linalg.lstsq(
                subset_design, translations[subset_indexes], rcond=None
            )
            residuals = np.linalg.norm(
                translations[allowed] - design[allowed] @ coefficients, axis=1
            )
            keep = max(minimum, int(math.ceil(0.7 * len(residuals))))
            score = float(
                np.sqrt(np.mean(np.square(np.partition(residuals, keep - 1)[:keep])))
            )
            if score < best_score:
                best_score = score
                best_coefficients = coefficients
        if best_coefficients is None:
            raise CalibrationError(
                "USB carriage motion is not independently observable from X/Y motion"
            )

        all_residuals = np.linalg.norm(
            translations - design @ best_coefficients, axis=1
        )
        _, residual_mask, _ = self._robust_rms(
            all_residuals[allowed].tolist(), minimum_cutoff=0.5
        )
        inlier_mask = np.zeros(len(views), dtype=bool)
        inlier_mask[allowed_indexes] = residual_mask
        if int(inlier_mask.sum()) < minimum:
            raise CalibrationError(
                "USB carriage fit retains insufficient robust PnP inliers"
            )
        coefficients, _, rank, _ = np.linalg.lstsq(
            design[inlier_mask], translations[inlier_mask], rcond=None
        )
        feature_spread = np.std(deltas[inlier_mask], axis=0)
        if bool(np.any(feature_spread <= 1e-9)):
            condition = math.inf
        else:
            standardized = (
                deltas[inlier_mask] - np.mean(deltas[inlier_mask], axis=0)
            ) / feature_spread
            condition = float(
                np.linalg.cond(
                    np.column_stack((np.ones(int(inlier_mask.sum())), standardized))
                )
            )
        return {
            "coefficients": coefficients,
            "inlier_mask": inlier_mask,
            "design_condition_number": condition,
            "observable": int(rank) == 4 and math.isfinite(condition),
        }

    def _translation_slope_diagnostics(
        self,
        views: list[dict],
        candidates: list[np.ndarray],
        inliers: np.ndarray,
    ) -> dict[str, Any]:
        try:
            regression = self._robust_translation_regression(
                views,
                candidates,
                minimum=4,
                eligible=inliers,
            )
        except CalibrationError as exc:
            return {"observable": False, "error": str(exc)}
        coefficients = np.asarray(regression["coefficients"], dtype=float)
        diagnostics = {
            "observable": bool(regression["observable"]),
            "design_condition_number": regression["design_condition_number"],
        }
        diagnostics.update(
            {
                command_axis: {
                    scanner_axis: round(
                        float(coefficients[index, scanner_index]), 6
                    )
                    for scanner_index, scanner_axis in enumerate(
                        ("scanner_x", "scanner_y", "scanner_z")
                    )
                }
                for index, command_axis in enumerate(
                    ("commanded_x", "commanded_y", "commanded_z"), start=1
                )
            }
        )
        return diagnostics

    @staticmethod
    def _extrinsic_fit_diagnostics(
        fits: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        diagnostics = {}
        for name, fit in fits.items():
            diagnostics[name] = {
                key: copy.deepcopy(fit[key])
                for key in (
                    "translation_rms_mm",
                    "rotation_rms_deg",
                    "robust_pnp_inliers",
                    "translation_slopes_mm_per_commanded_mm",
                    "accepted",
                    "score",
                )
            }
            carriage_fit = fit["carriage_fit"]
            diagnostics[name]["carriage_fit"] = (
                None
                if carriage_fit is None
                else {
                    key: copy.deepcopy(value)
                    for key, value in carriage_fit.items()
                    if key != "inlier_mask"
                }
            )
        return diagnostics

    def _validate_x_scale(self) -> dict:
        self._set_phase("x-scale", "Validating X scale and repeatability", 60)
        signed_scale = float(self._motion_model["x_mm_per_commanded_mm"])
        scale = abs(signed_scale)
        rms = float(self._motion_model["x_translation_rms_mm"])
        tolerance = float(self._config.get("x_scale_tolerance_fraction", 0.05))
        maximum_repeatability = float(self._config.get("maximum_x_repeatability_mm", 3.0))
        accepted = abs(scale - 1.0) <= tolerance and rms <= maximum_repeatability
        result = {
            "accepted": accepted,
            "measured_mm_per_commanded_mm": scale,
            "signed_mm_per_commanded_mm": signed_scale,
            "command_direction": self._motion_model["x_direction"],
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
            "command_radians_per_mm": float(
                self._motion_model["y_radians_per_commanded_mm"]
            ),
            "commanded_mm_per_revolution": float(
                self._motion_model["y_commanded_mm_per_revolution"]
            ),
            "command_direction": self._motion_model["y_direction"],
            "reference_pose_mm": copy.deepcopy(
                self._motion_model["reference_pose_mm"]
            ),
            "source": "measured_diameter",
            "quality": {
                "accepted": True,
                "diameter_source": "operator_measured_turntable",
                "formula": "pi * diameter_mm",
                "derived_mm_per_revolution": circumference,
                "observed_rotation_rms_deg": float(
                    self._motion_model["y_rotation_rms_deg"]
                ),
                "candidate_residuals": copy.deepcopy(
                    self._motion_model["candidate_residuals"]["y"]
                ),
            },
        }

    def _calibrate_lasers(
        self,
        poses: list[dict[str, float]],
        calibration: Mapping[str, Any],
        checkerboard_views: Mapping[str, list[dict]] | None = None,
    ) -> dict:
        self._set_phase("laser-planes", "Fitting left and right laser planes", 68)
        samples: dict[str, dict[str, list[list[float]]]] = {
            side: {name: [] for name in ("pi", "usb")}
            for side in ("left", "right")
        }
        sample_pose_indexes: dict[str, dict[str, list[int]]] = {
            side: {name: [] for name in ("pi", "usb")}
            for side in ("left", "right")
        }
        accepted_pose_indexes: dict[str, dict[str, set[int]]] = {
            side: {name: set() for name in ("pi", "usb")}
            for side in ("left", "right")
        }
        try:
            for pose_index, pose in enumerate(poses):
                self._check_cancelled()
                self._move_to(pose)
                self._sleep_interruptible(float(self._config.get("settle_s", 0.25)))
                self._lasers_off()
                ambient = {"pi": self._capture("pi")}
                usb_ambient_error = None
                try:
                    ambient["usb"] = self._capture("usb")
                except CalibrationCancelled:
                    raise
                except Exception as exc:
                    usb_ambient_error = str(exc)
                for side in ("left", "right"):
                    self._laser(side, True)
                    try:
                        self._sleep_interruptible(
                            float(self._config.get("laser_settle_s", 0.1))
                        )
                        for name in ("pi", "usb"):
                            checkerboard_view = self._checkerboard_view_for_pose(
                                checkerboard_views, name, pose
                            )
                            unavailable_reason = None
                            if checkerboard_views is not None and checkerboard_view is None:
                                unavailable_reason = (
                                    "no accepted exact-pose checkerboard view"
                                )
                            if name == "usb" and usb_ambient_error is not None:
                                unavailable_reason = (
                                    f"optional USB ambient capture failed: "
                                    f"{usb_ambient_error}"
                                )
                            if unavailable_reason is not None:
                                extracted = {
                                    "points": [],
                                    "diagnostic": {
                                        "accepted": False,
                                        "reason": unavailable_reason,
                                    },
                                }
                            else:
                                try:
                                    laser = self._capture(name)
                                    extracted = self._laser_board_points(
                                        name,
                                        side,
                                        ambient[name],
                                        laser,
                                        pose,
                                        calibration,
                                        checkerboard_view=checkerboard_view,
                                    )
                                except CalibrationCancelled:
                                    raise
                                except Exception as exc:
                                    if name == "pi":
                                        raise
                                    extracted = {
                                        "points": [],
                                        "diagnostic": {
                                            "accepted": False,
                                            "reason": (
                                                "optional USB laser observation "
                                                f"failed: {exc}"
                                            ),
                                        },
                                    }
                            diagnostic = copy.deepcopy(extracted["diagnostic"])
                            diagnostic.update(
                                pose_index=pose_index,
                                pose=copy.deepcopy(dict(pose)),
                                camera=name,
                                side=side,
                                fit_role=(
                                    "primary"
                                    if name == "pi"
                                    else "optional_cross_validation"
                                ),
                                checkerboard_source=(
                                    "cached"
                                    if checkerboard_view is not None
                                    else "missing-cache"
                                    if checkerboard_views is not None
                                    else diagnostic.get(
                                        "checkerboard_source", "ambient-detection"
                                    )
                                ),
                            )
                            with self._lock:
                                self._status["laser_views"][side][name].append(
                                    diagnostic
                                )
                            if diagnostic["accepted"]:
                                samples[side][name].extend(extracted["points"])
                                sample_pose_indexes[side][name].extend(
                                    [pose_index] * len(extracted["points"])
                                )
                                accepted_pose_indexes[side][name].add(pose_index)
                    finally:
                        self._laser(side, False)
        finally:
            self._lasers_off()
        result = {}
        maximum_rms = min(
            float(self._config.get("maximum_laser_plane_rms_mm", 2.0)),
            2.0,
        )
        if not math.isfinite(maximum_rms) or maximum_rms <= 0:
            raise CalibrationError(
                "maximum laser plane RMS must be finite, positive, and no "
                "greater than 2mm"
            )
        minimum_points = int(self._config.get("minimum_laser_points", 30))
        minimum_views = int(self._config.get("minimum_laser_views", 3))
        minimum_orientations = int(
            self._config.get("minimum_laser_board_orientations", 3)
        )
        for side in ("left", "right"):
            pi_poses = [
                poses[index]
                for index in sorted(accepted_pose_indexes[side]["pi"])
            ]
            orientation_count = self._independent_board_orientation_count(
                pi_poses
            )
            sufficiency = {
                "accepted": False,
                "primary_camera": "pi",
                "points": len(samples[side]["pi"]),
                "accepted_camera_views": len(
                    accepted_pose_indexes[side]["pi"]
                ),
                "accepted_poses": len(pi_poses),
                "independent_board_orientations": orientation_count,
                "minimum_points": minimum_points,
                "minimum_views": minimum_views,
                "minimum_board_orientations": minimum_orientations,
            }
            if (
                len(samples[side]["pi"]) < minimum_points
                or len(pi_poses) < minimum_views
                or orientation_count < minimum_orientations
            ):
                with self._lock:
                    self._status["metrics"][f"laser_{side}"] = copy.deepcopy(
                        sufficiency
                    )
                raise CalibrationError(
                    f"{side} laser has insufficient valid Pi-camera checkerboard "
                    f"intersections: {len(samples[side]['pi'])} points, "
                    f"{len(pi_poses)} poses, "
                    f"{orientation_count} independent orientations; requires "
                    f"{minimum_points} points, {minimum_views} poses, "
                    f"{minimum_orientations} orientations"
                )
            normal, offset, quality = fit_plane_robust(
                samples[side]["pi"],
                minimum_points=minimum_points,
                return_inlier_mask=True,
            )
            inlier_mask = np.asarray(quality.pop("inlier_mask"), dtype=bool)
            inlier_pose_indexes = sorted(
                set(
                    np.asarray(sample_pose_indexes[side]["pi"], dtype=int)[
                        inlier_mask
                    ].tolist()
                )
            )
            inlier_poses = [poses[index] for index in inlier_pose_indexes]
            inlier_orientation_count = self._independent_board_orientation_count(
                inlier_poses
            )
            if (
                len(inlier_poses) < minimum_views
                or inlier_orientation_count < minimum_orientations
            ):
                quality.update(
                    accepted=False,
                    primary_camera="pi",
                    views=len(inlier_poses),
                    independent_board_orientations=inlier_orientation_count,
                    minimum_views=minimum_views,
                    minimum_board_orientations=minimum_orientations,
                )
                with self._lock:
                    self._status["metrics"][f"laser_{side}"] = copy.deepcopy(
                        quality
                    )
                raise CalibrationError(
                    f"{side} laser robust fit retains only "
                    f"{len(inlier_poses)} Pi poses and "
                    f"{inlier_orientation_count} independent orientations; "
                    f"requires {minimum_views} poses and "
                    f"{minimum_orientations} orientations"
                )
            quality.update(
                primary_camera="pi",
                views=len(inlier_poses),
                camera_views=len(accepted_pose_indexes[side]["pi"]),
                rejected_camera_views=len(poses)
                - len(accepted_pose_indexes[side]["pi"]),
                independent_board_orientations=inlier_orientation_count,
                minimum_views=minimum_views,
                minimum_board_orientations=minimum_orientations,
            )
            quality["maximum_rms_mm"] = maximum_rms
            if quality["rms_mm"] > maximum_rms:
                quality["accepted"] = False
                with self._lock:
                    self._status["metrics"][f"laser_{side}"] = copy.deepcopy(
                        quality
                    )
                raise CalibrationError(
                    f"{side} laser plane RMS {quality['rms_mm']:.2f}mm exceeds "
                    f"{maximum_rms:.2f}mm"
                )
            usb_poses = [
                poses[index]
                for index in sorted(accepted_pose_indexes[side]["usb"])
            ]
            usb_orientations = self._independent_board_orientation_count(
                usb_poses
            )
            usb_cross_validation = {
                "performed": False,
                "accepted": None,
                "points": len(samples[side]["usb"]),
                "views": len(usb_poses),
                "independent_board_orientations": usb_orientations,
            }
            if (
                len(samples[side]["usb"]) >= minimum_points
                and len(usb_poses) >= minimum_views
                and usb_orientations >= minimum_orientations
            ):
                usb_values = np.asarray(samples[side]["usb"], dtype=float)
                usb_residual = float(
                    np.sqrt(np.mean((usb_values @ normal + offset) ** 2))
                )
                usb_cross_validation.update(
                    performed=True,
                    accepted=usb_residual <= maximum_rms,
                    rms_mm=usb_residual,
                    maximum_rms_mm=maximum_rms,
                )
                if usb_residual > maximum_rms:
                    usb_cross_validation["reason"] = (
                        f"optional USB cross-validation RMS {usb_residual:.2f}mm "
                        f"exceeds {maximum_rms:.2f}mm; Pi plane remains authoritative"
                    )
            quality["usb_cross_validation"] = usb_cross_validation
            result[side] = {
                "normal": normal.tolist(),
                "offset_mm": offset,
                "source": "pi_checkerboard_structured_light",
                "quality": quality,
            }
            with self._lock:
                self._status["metrics"][f"laser_{side}"] = copy.deepcopy(quality)
        return result

    @staticmethod
    def _checkerboard_view_for_pose(
        checkerboard_views: Mapping[str, list[dict]] | None,
        camera_name: str,
        pose: Mapping[str, float],
    ) -> dict | None:
        if checkerboard_views is None:
            return None
        for view in checkerboard_views.get(camera_name, []):
            view_pose = view.get("pose", {})
            if all(
                math.isclose(
                    float(view_pose.get(axis, math.nan)),
                    float(pose[axis]),
                    rel_tol=0,
                    abs_tol=1e-6,
                )
                for axis in ("x", "y", "z")
            ):
                return view
        return None

    def _independent_board_orientation_count(
        self, poses: list[Mapping[str, float]]
    ) -> int:
        minimum_separation = float(
            self._config.get("minimum_laser_orientation_separation_deg", 4.0)
        )
        if not math.isfinite(minimum_separation) or minimum_separation <= 0:
            raise CalibrationError(
                "minimum laser orientation separation must be finite and positive"
            )
        selected: list[np.ndarray] = []
        for pose in poses:
            normal = self._board_to_scanner(pose)[:3, 2]
            normal = normal / np.linalg.norm(normal)
            if all(
                math.degrees(
                    math.acos(
                        np.clip(abs(float(np.dot(normal, prior))), 0.0, 1.0)
                    )
                )
                >= minimum_separation
                for prior in selected
            ):
                selected.append(normal)
        return len(selected)

    def _laser_board_points(
        self,
        camera_name: str,
        side: str,
        ambient_jpeg: bytes,
        laser_jpeg: bytes,
        pose: Mapping[str, float],
        calibration: Mapping[str, Any],
        *,
        checkerboard_view: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        ambient = self._cv.imdecode(np.frombuffer(ambient_jpeg, np.uint8), self._cv.IMREAD_COLOR)
        laser = self._cv.imdecode(np.frombuffer(laser_jpeg, np.uint8), self._cv.IMREAD_COLOR)
        if ambient is None or laser is None or ambient.shape != laser.shape:
            return {
                "points": [],
                "diagnostic": {
                    "accepted": False,
                    "reason": "camera frames could not be decoded consistently",
                },
            }
        checkerboard_source = "cached"
        if checkerboard_view is None:
            checkerboard_source = "ambient-detection"
            try:
                checkerboard_view = self._detect_checkerboard(ambient_jpeg, pose)
            except (CheckerboardDetectionRejected, CheckerboardDetectionTimeout) as exc:
                return {
                    "points": [],
                    "diagnostic": {
                        "accepted": False,
                        "reason": f"ambient checkerboard detection failed: {exc}",
                        "checkerboard_source": "ambient-detection",
                    },
                }
        pixels, diagnostic = extract_laser_line_pixels(
            self._cv,
            ambient,
            laser,
            checkerboard_view.get("corners"),
            config=self._config,
        )
        diagnostic["checkerboard_source"] = checkerboard_source
        if not pixels:
            return {"points": [], "diagnostic": diagnostic}
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
            carriage_direction = np.asarray(
                camera.get("carriage_direction", [0.0, 0.0, 1.0]), dtype=float
            )
            transform[:3, 3] += carriage_direction * (pose["z"] - reference)
        origin = transform[:3, 3]
        board_transform = self._board_to_scanner(pose)
        plane_point = board_transform[:3, 3]
        plane_normal = board_transform[:3, 2]
        result = []
        rejected_rays = 0
        for x, y in normalized:
            direction = transform[:3, :3] @ np.array([x, y, 1.0])
            direction /= np.linalg.norm(direction)
            denominator = float(np.dot(plane_normal, direction))
            if abs(denominator) <= 1e-9:
                rejected_rays += 1
                continue
            distance = float(np.dot(plane_normal, plane_point - origin) / denominator)
            if 0 < distance <= float(self._config.get("maximum_ray_distance_mm", 2000)):
                result.append((origin + direction * distance).tolist())
            else:
                rejected_rays += 1
        minimum_points = int(
            self._config.get(
                "minimum_laser_points_per_view",
                min(10, int(self._config.get("minimum_laser_line_rows", 12))),
            )
        )
        diagnostic.update(points=len(result), rejected_rays=rejected_rays)
        if len(result) < minimum_points:
            diagnostic.update(
                accepted=False,
                reason=(
                    f"only {len(result)} valid board-plane intersections; "
                    f"{minimum_points} required"
                ),
            )
            return {"points": [], "diagnostic": diagnostic}
        diagnostic["accepted"] = True
        return {"points": result, "diagnostic": diagnostic}

    def _calibrate_lidar(
        self,
        poses: list[dict[str, float]],
        calibration: Mapping[str, Any],
        inputs: Mapping[str, Any],
    ) -> dict:
        self._set_phase("lidar", "Validating measured TF-Luna beam transform", 84)
        transform = transform_from_beam(inputs.get("origin_mm"), inputs.get("direction"))
        reference_z = float(
            inputs.get("reference_z_mm", self._reference_pose["z"])
        )
        usb = calibration.get("cameras", {}).get("usb", {})
        if usb.get("carriage_axis") != "z":
            raise CalibrationError(
                "TF-Luna carriage correction is not observable without the "
                "validated USB Z carriage fit"
            )
        carriage_direction = np.asarray(
            usb.get("carriage_direction"), dtype=float
        )
        if (
            carriage_direction.shape != (3,)
            or not np.isfinite(carriage_direction).all()
            or np.linalg.norm(carriage_direction) <= 1e-9
        ):
            raise CalibrationError(
                "TF-Luna carriage correction is not observable because the "
                "validated USB carriage vector is missing"
            )
        carriage_scale = float(np.linalg.norm(carriage_direction))
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
            current[:3, 3] += carriage_direction * (pose["z"] - reference_z)
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
            "carriage_direction": carriage_direction.tolist(),
            "carriage_scale_mm_per_commanded_mm": carriage_scale,
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
                "carriage_source": "validated_usb_carriage_fit",
            },
        }

    def _board_to_scanner(self, pose: Mapping[str, float]) -> np.ndarray:
        return self._board_transform(
            pose,
            x_scale=float(self._motion_model["x_mm_per_commanded_mm"]),
            y_scale=float(self._motion_model["y_radians_per_commanded_mm"]),
        )

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

    def _robust_average_transforms(
        self, transforms: list[np.ndarray]
    ) -> tuple[np.ndarray, float, float, list[dict[str, Any]]]:
        selected = np.ones(len(transforms), dtype=bool)
        for _ in range(3):
            average, _, _ = self._average_transforms(
                [transform for transform, keep in zip(transforms, selected) if keep]
            )
            translation_residuals = [
                float(np.linalg.norm(transform[:3, 3] - average[:3, 3]))
                for transform in transforms
            ]
            rotation_residuals = [
                self._rotation_residual_deg(average[:3, :3], transform[:3, :3])
                for transform in transforms
            ]
            _, translation_mask, _ = self._robust_rms(
                translation_residuals, minimum_cutoff=0.5
            )
            _, rotation_mask, _ = self._robust_rms(
                rotation_residuals, minimum_cutoff=0.1
            )
            updated = translation_mask & rotation_mask
            if not bool(updated.any()) or np.array_equal(updated, selected):
                break
            selected = updated
        average, _, _ = self._average_transforms(
            [transform for transform, keep in zip(transforms, selected) if keep]
        )
        translation_residuals = [
            float(np.linalg.norm(transform[:3, 3] - average[:3, 3]))
            for transform in transforms
        ]
        rotation_residuals = [
            self._rotation_residual_deg(average[:3, :3], transform[:3, :3])
            for transform in transforms
        ]
        translation_rms = float(
            np.sqrt(
                np.mean(
                    np.square(
                        np.asarray(translation_residuals, dtype=float)[selected]
                    )
                )
            )
        )
        rotation_rms = float(
            np.sqrt(
                np.mean(
                    np.square(np.asarray(rotation_residuals, dtype=float)[selected])
                )
            )
        )
        details = [
            {
                "view": index + 1,
                "translation_residual_mm": round(translation_residuals[index], 5),
                "rotation_residual_deg": round(rotation_residuals[index], 5),
                "inlier": bool(selected[index]),
            }
            for index in range(len(transforms))
        ]
        return average, translation_rms, rotation_rms, details

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
                "x": (
                    "checkerboard normal at Y reference; commanded X sign is "
                    "estimated from PnP"
                ),
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

    def _capture(self, name: str, *, timeout_s: float | None = None) -> bytes:
        camera = self._cameras[name]
        timeout = (
            float(timeout_s)
            if timeout_s is not None
            else float(self._config.get("capture_timeout_s", 5.0))
        )
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
        if self._lidar_output_restore_required:
            try:
                self._set_lidar_output_enabled(True)
            except Exception as exc:
                message = f"failed to restore TF-Luna ranging output: {exc}"
                with self._lock:
                    current = self._status.get("error")
                    error = f"{current}; {message}" if current else message
                    self._status.update(phase="error", step=message, error=error)
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
