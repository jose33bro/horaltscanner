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


class LaserPlaneConsensusError(CalibrationError):
    """Pose-aware laser-plane consensus failed with reportable diagnostics."""

    def __init__(self, message: str, quality: Mapping[str, Any]):
        super().__init__(message)
        self.quality = copy.deepcopy(dict(quality))


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
MINIMUM_DIRECT_Z_CONTRASTS = 3
DIRECT_Z_ESTIMATOR = "same_xy_z_contrast_geometric_median"
RESIDUALIZED_Z_ESTIMATOR = "z_residualized_against_commanded_x_y"


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


def _gaussian_blur_rows(cv: Any, image: np.ndarray, sigma: float) -> np.ndarray:
    radius = max(1, int(math.ceil(3.0 * sigma)))
    return cv.GaussianBlur(
        image,
        (radius * 2 + 1, 1),
        sigmaX=sigma,
        sigmaY=0,
        borderType=cv.BORDER_REPLICATE,
    )


def _contiguous_row_groups(rows: np.ndarray, row_stride: int) -> list[np.ndarray]:
    if not len(rows):
        return []
    ordered = np.sort(np.asarray(rows, dtype=float))
    split_at = np.flatnonzero(np.diff(ordered) > row_stride * 2.0) + 1
    return [group for group in np.split(ordered, split_at) if len(group)]


def _robust_ridge_line(
    selected: np.ndarray,
    *,
    maximum_residual: float,
    inlier_tolerance: float,
    minimum_rows: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit x(y) from a bounded Theil-Sen seed, then trim row outliers."""
    ordered = selected[np.argsort(selected[:, 1])]
    ordinary = np.polyfit(ordered[:, 1], ordered[:, 0], 1)
    ordinary_residuals = ordered[:, 0] - np.polyval(ordinary, ordered[:, 1])
    if float(np.sqrt(np.mean(np.square(ordinary_residuals)))) <= maximum_residual:
        return ordered, np.asarray(ordinary, dtype=float)

    sample = ordered
    if len(sample) > 256:
        indexes = np.linspace(0, len(sample) - 1, 256).round().astype(int)
        sample = sample[indexes]
    first, second = np.triu_indices(len(sample), 1)
    delta_rows = sample[second, 1] - sample[first, 1]
    usable = np.abs(delta_rows) > 1e-9
    if not np.any(usable):
        raise CalibrationError("laser ridge rows do not span a line")
    slopes = (
        sample[second[usable], 0] - sample[first[usable], 0]
    ) / delta_rows[usable]
    slope = float(np.median(slopes))
    intercept = float(np.median(ordered[:, 0] - slope * ordered[:, 1]))
    seed_residuals = ordered[:, 0] - (slope * ordered[:, 1] + intercept)
    retained = ordered[np.abs(seed_residuals) <= inlier_tolerance]
    minimum_retained = max(minimum_rows, int(math.ceil(len(ordered) * 0.88)))
    if len(retained) < minimum_retained:
        return ordered, np.asarray(ordinary, dtype=float)
    while len(retained) >= minimum_retained:
        slope, intercept = np.polyfit(retained[:, 1], retained[:, 0], 1)
        residuals = retained[:, 0] - (slope * retained[:, 1] + intercept)
        if float(np.sqrt(np.mean(np.square(residuals)))) <= maximum_residual:
            break
        if len(retained) == minimum_retained:
            return retained, np.array([float(slope), float(intercept)], dtype=float)
        retained = np.delete(retained, int(np.argmax(np.abs(residuals))), axis=0)
    removed_rows = np.setdiff1d(ordered[:, 1], retained[:, 1])
    ordered_steps = np.diff(np.unique(ordered[:, 1]))
    inferred_stride = max(
        1,
        int(round(float(np.median(ordered_steps)))) if len(ordered_steps) else 1,
    )
    maximum_outlier_groups = max(3, int(math.ceil(len(ordered) * 0.04)))
    maximum_outlier_group_rows = max(4, int(math.ceil(len(ordered) * 0.08)))
    outlier_groups = _contiguous_row_groups(removed_rows, inferred_stride)
    if (
        len(outlier_groups) > maximum_outlier_groups
        or any(len(group) > maximum_outlier_group_rows for group in outlier_groups)
    ):
        return ordered, np.asarray(ordinary, dtype=float)
    return retained, np.array([float(slope), float(intercept)], dtype=float)


def _checker_row_crossings(
    corner_grid: np.ndarray,
    coefficients: np.ndarray,
) -> np.ndarray:
    """Intersect the fitted ridge with each perspective-projected checker row."""
    slope, intercept = (float(value) for value in coefficients)
    crossings = []
    for checker_row in corner_grid:
        design = np.column_stack(
            (
                checker_row[:, 0],
                checker_row[:, 1],
                np.ones(len(checker_row), dtype=float),
            )
        )
        _, _, vectors = np.linalg.svd(design, full_matrices=False)
        line_x, line_y, line_offset = vectors[-1]
        denominator = line_x * slope + line_y
        if abs(float(denominator)) <= 1e-9:
            continue
        row = -float(line_x * intercept + line_offset) / float(denominator)
        column = slope * row + intercept
        minimum_column = float(np.min(checker_row[:, 0]))
        maximum_column = float(np.max(checker_row[:, 0]))
        if (
            math.isfinite(row)
            and math.isfinite(column)
            and minimum_column - 1.0 <= column <= maximum_column + 1.0
        ):
            crossings.append(row)
    return np.sort(np.asarray(crossings, dtype=float))


def _sample_along_line(
    image: np.ndarray,
    coefficients: np.ndarray,
    start_row: float,
    stop_row: float,
) -> np.ndarray:
    height, width = image.shape[:2]
    first = max(0, int(math.ceil(min(start_row, stop_row))))
    last = min(height - 1, int(math.floor(max(start_row, stop_row))))
    if last < first:
        return np.empty(0, dtype=float)
    rows = np.arange(first, last + 1, dtype=int)
    columns = np.rint(np.polyval(coefficients, rows)).astype(int)
    valid = (columns >= 0) & (columns < width)
    return np.asarray(image[rows[valid], columns[valid]], dtype=float)


def _sample_line_band_max(
    image: np.ndarray,
    coefficients: np.ndarray,
    start_row: float,
    stop_row: float,
    radius: int,
) -> np.ndarray:
    height, width = image.shape[:2]
    first = max(0, int(math.ceil(min(start_row, stop_row))))
    last = min(height - 1, int(math.floor(max(start_row, stop_row))))
    if last < first:
        return np.empty(0, dtype=float)
    rows = np.arange(first, last + 1, dtype=int)
    centers = np.rint(np.polyval(coefficients, rows)).astype(int)
    maxima = []
    for row, center in zip(rows, centers):
        left = max(0, int(center) - radius)
        right = min(width, int(center) + radius + 1)
        if right > left:
            maxima.append(float(np.max(image[row, left:right])))
    return np.asarray(maxima, dtype=float)


def _classify_checker_gaps(
    *,
    corner_grid: np.ndarray,
    selected: np.ndarray,
    coefficients: np.ndarray,
    row_stride: int,
    strict_gap_limit: float,
    maximum_residual: float,
    maximum_width: float,
    minimum_prominence: float,
    minimum_chromatic_support: float,
    minimum_sharpness_ratio: float,
    ambiguity_ratio: float,
    ridge_response: np.ndarray,
    fine_response: np.ndarray,
    chromatic_response: np.ndarray,
    ambient_luminance: np.ndarray,
    reference_luminance: float,
) -> dict[str, Any]:
    ordered_indexes = np.argsort(selected[:, 1])
    ordered = selected[ordered_indexes]
    line_rows = ordered[:, 1]
    gaps = np.diff(line_rows)
    raw_max_gap = float(np.max(gaps)) if len(gaps) else math.inf
    crossings = _checker_row_crossings(corner_grid, coefficients)
    vertical_pitches = np.diff(crossings)
    vertical_pitches = vertical_pitches[vertical_pitches > row_stride]
    path_scale = math.hypot(1.0, float(coefficients[0]))
    projected_pitches = vertical_pitches * path_scale
    gap_limits = projected_pitches * 1.25

    split_indexes = np.flatnonzero(gaps > strict_gap_limit)
    starts = np.concatenate(([0], split_indexes + 1))
    stops = np.concatenate((split_indexes + 1, [len(line_rows)]))
    segments = []
    for start, stop in zip(starts, stops):
        points = ordered[start:stop]
        if len(points) >= 2 and float(np.ptp(points[:, 1])) > 1e-9:
            local_coefficients = np.polyfit(points[:, 1], points[:, 0], 1)
            local_residuals = points[:, 0] - np.polyval(
                local_coefficients, points[:, 1]
            )
            local_rms = float(np.sqrt(np.mean(np.square(local_residuals))))
        else:
            local_coefficients = coefficients
            local_rms = math.inf
        segments.append(
            {
                "start": int(start),
                "stop": int(stop),
                "span": float(
                    max(line_rows[stop - 1] - line_rows[start], 0.0) * path_scale
                ),
                "rms": local_rms,
                "coefficients": local_coefficients,
            }
        )
    gap_segments = {
        int(gap_index): (segment_index, segment_index + 1)
        for segment_index, gap_index in enumerate(split_indexes)
    }
    median_pitch = (
        float(np.median(projected_pitches)) if len(projected_pitches) else math.inf
    )
    long_segment_threshold = max(
        row_stride * 3.0 * path_scale,
        median_pitch * 0.5,
    )
    long_segments = sum(
        segment["span"] >= long_segment_threshold
        and segment["rms"] <= maximum_residual
        for segment in segments
    )

    bridged: set[int] = set()
    response_p90: list[float] = []
    boundary_contrasts: list[float] = []
    rejection_counts: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    if len(crossings) >= 2:
        minimum_contrast = max(6.0, reference_luminance * 0.08)
        for gap_index in split_indexes:
            lower = float(line_rows[gap_index])
            upper = float(line_rows[gap_index + 1])
            missing_start = lower + row_stride
            missing_stop = upper - row_stride
            missing_length = max(upper - lower - row_stride, 0.0) * path_scale
            segment_indexes = gap_segments[int(gap_index)]
            left_segment = segments[segment_indexes[0]]
            right_segment = segments[segment_indexes[1]]
            if (
                left_segment["rms"] > maximum_residual
                or right_segment["rms"] > maximum_residual
            ):
                reject("noncoherent_endpoints")
                continue

            paired_points = np.vstack(
                (
                    ordered[left_segment["start"] : left_segment["stop"]],
                    ordered[right_segment["start"] : right_segment["stop"]],
                )
            )
            paired_coefficients = np.polyfit(
                paired_points[:, 1], paired_points[:, 0], 1
            )
            paired_residuals = paired_points[:, 0] - np.polyval(
                paired_coefficients, paired_points[:, 1]
            )
            paired_rms = float(
                np.sqrt(np.mean(np.square(paired_residuals)))
            )
            left_count = left_segment["stop"] - left_segment["start"]
            per_segment_pair_rms = (
                float(
                    np.sqrt(
                        np.mean(
                            np.square(paired_residuals[:left_count])
                        )
                    )
                ),
                float(
                    np.sqrt(
                        np.mean(
                            np.square(paired_residuals[left_count:])
                        )
                    )
                ),
            )
            segment_offset_difference = abs(
                float(np.mean(paired_residuals[:left_count]))
                - float(np.mean(paired_residuals[left_count:]))
            )
            if (
                paired_rms > maximum_residual
                or max(per_segment_pair_rms) > maximum_residual
                or segment_offset_difference > maximum_residual
            ):
                reject("noncoherent_endpoints")
                continue

            paired_crossings = _checker_row_crossings(
                corner_grid, paired_coefficients
            )
            aligned_pair = None
            for boundary_index in range(len(paired_crossings) - 1):
                first_boundary = float(paired_crossings[boundary_index])
                second_boundary = float(paired_crossings[boundary_index + 1])
                pitch_y = second_boundary - first_boundary
                pitch = pitch_y * path_scale
                alignment_tolerance = max(
                    row_stride * 2.0 * path_scale,
                    pitch * 0.18,
                )
                start_error = abs(missing_start - first_boundary) * path_scale
                stop_error = abs(missing_stop - second_boundary) * path_scale
                if (
                    0.5 * pitch <= missing_length <= 1.25 * pitch
                    and start_error <= alignment_tolerance
                    and stop_error <= alignment_tolerance
                ):
                    aligned_pair = (first_boundary, second_boundary, pitch_y, pitch)
                    break
            if aligned_pair is None:
                reject("not_one_checker_square")
                continue

            first_boundary, second_boundary, pitch_y, pitch = aligned_pair
            minimum_adjacent_span = max(
                row_stride * 3.0 * path_scale,
                pitch * 0.35,
            )
            if (
                left_segment["span"] < minimum_adjacent_span
                or right_segment["span"] < minimum_adjacent_span
            ):
                reject("insufficient_long_segments")
                continue

            missing_response = _sample_line_band_max(
                ridge_response,
                paired_coefficients,
                missing_start,
                missing_stop,
                max(1, int(math.ceil(maximum_width * 2.0))),
            )
            if not len(missing_response):
                reject("missing_response_unavailable")
                continue
            local_response_p90 = float(np.percentile(missing_response, 90))
            active_fraction = float(
                np.mean(missing_response >= minimum_prominence)
            )
            if (
                local_response_p90 > minimum_prominence * 0.9
                or active_fraction > 0.2
            ):
                core_radius = max(1, int(math.ceil(maximum_width * 0.5)))
                band_radius = max(
                    core_radius + 1,
                    int(math.ceil(maximum_width * 2.0)),
                )
                first_row = max(0, int(math.ceil(missing_start)))
                last_row = min(
                    ridge_response.shape[0] - 1,
                    int(math.floor(missing_stop)),
                )
                evaluated_rows = max(last_row - first_row + 1, 0)
                active_rows = 0
                centered_rows = 0
                response_threshold = minimum_prominence * 0.9
                for row in range(first_row, last_row + 1):
                    center = int(round(float(np.polyval(paired_coefficients, row))))
                    left = max(0, center - band_radius)
                    right = min(
                        ridge_response.shape[1],
                        center + band_radius + 1,
                    )
                    if right <= left:
                        continue
                    columns = np.arange(left, right)
                    offsets = np.abs(columns - center)
                    responses = np.asarray(
                        ridge_response[row, left:right],
                        dtype=float,
                    )
                    core_indexes = np.flatnonzero(offsets <= core_radius)
                    off_axis_indexes = np.flatnonzero(offsets > core_radius)
                    if not len(core_indexes):
                        continue
                    core_index = int(
                        core_indexes[
                            int(np.argmax(responses[core_indexes]))
                        ]
                    )
                    core_peak = float(responses[core_index])
                    off_axis_peak = (
                        float(np.max(responses[off_axis_indexes]))
                        if len(off_axis_indexes)
                        else 0.0
                    )
                    if max(core_peak, off_axis_peak) < response_threshold:
                        continue
                    active_rows += 1
                    peak_column = left + core_index
                    if (
                        core_peak < response_threshold
                        or float(fine_response[row, peak_column])
                        < core_peak * minimum_sharpness_ratio
                        or float(chromatic_response[row, peak_column])
                        < minimum_chromatic_support * 0.5
                        or off_axis_peak >= core_peak * ambiguity_ratio
                    ):
                        continue
                    centered_rows += 1
                minimum_centered_rows = max(
                    3, int(math.ceil(evaluated_rows * 0.2))
                )
                centered_fraction = centered_rows / max(active_rows, 1)
                if (
                    centered_rows < minimum_centered_rows
                    or centered_fraction < ambiguity_ratio
                ):
                    reject("ridge_response_not_low")
                    continue

            window = max(2.0, pitch_y * 0.18)
            first_context = _sample_along_line(
                ambient_luminance,
                paired_coefficients,
                first_boundary - 2.0 * window,
                first_boundary + 2.0 * window,
            )
            second_context = _sample_along_line(
                ambient_luminance,
                paired_coefficients,
                second_boundary - 2.0 * window,
                second_boundary + 2.0 * window,
            )
            if not all(len(values) for values in (first_context, second_context)):
                reject("reflectance_samples_unavailable")
                continue
            first_contrast = float(
                np.percentile(first_context, 90) - np.percentile(first_context, 10)
            )
            second_contrast = float(
                np.percentile(second_context, 90) - np.percentile(second_context, 10)
            )
            gap_reflectance = _sample_along_line(
                ambient_luminance,
                paired_coefficients,
                first_boundary + row_stride,
                second_boundary - row_stride,
            )
            before_reflectance = _sample_along_line(
                ambient_luminance,
                paired_coefficients,
                first_boundary - pitch_y + row_stride,
                first_boundary - row_stride,
            )
            after_reflectance = _sample_along_line(
                ambient_luminance,
                paired_coefficients,
                second_boundary + row_stride,
                second_boundary + pitch_y - row_stride,
            )
            if not all(
                len(values)
                for values in (
                    gap_reflectance,
                    before_reflectance,
                    after_reflectance,
                )
            ):
                reject("reflectance_samples_unavailable")
                continue
            gap_level = float(np.median(gap_reflectance))
            before_level = float(np.median(before_reflectance))
            after_level = float(np.median(after_reflectance))
            adjacent_level = min(before_level, after_level)
            if (
                first_contrast < minimum_contrast
                or second_contrast < minimum_contrast
                or gap_level > adjacent_level - minimum_contrast * 0.5
            ):
                reject("reflectance_boundary_mismatch")
                continue

            bridged.add(int(gap_index))
            response_p90.append(local_response_p90)
            boundary_contrasts.append(min(first_contrast, second_contrast))
    elif len(split_indexes):
        reason = "checker_geometry_unavailable"
        for _ in split_indexes:
            reject(reason)

    unexplained_gaps = [
        float(gap)
        for gap_index, gap in enumerate(gaps)
        if gap_index not in bridged
    ]
    unexplained_max_gap = max(unexplained_gaps, default=0.0)
    return {
        "raw_max_gap_px": max(raw_max_gap, 0.0),
        "bridged_checker_gaps": len(bridged),
        "unexplained_max_gap_px": max(unexplained_max_gap, 0.0),
        "projected_checker_pitch_px_median": (
            float(np.median(projected_pitches)) if len(projected_pitches) else 0.0
        ),
        "projected_checker_pitch_px_min": (
            float(np.min(projected_pitches)) if len(projected_pitches) else 0.0
        ),
        "projected_checker_pitch_px_max": (
            float(np.max(projected_pitches)) if len(projected_pitches) else 0.0
        ),
        "checker_gap_limit_px_median": (
            float(np.median(gap_limits)) if len(gap_limits) else 0.0
        ),
        "checker_gap_limit_px_max": (
            float(np.max(gap_limits)) if len(gap_limits) else 0.0
        ),
        "observed_line_segments": len(segments),
        "sufficiently_long_line_segments": int(long_segments),
        "checker_gap_response_p90_max": max(response_p90, default=0.0),
        "checker_boundary_contrast_min": min(boundary_contrasts, default=0.0),
        "checker_gap_rejection_counts": rejection_counts,
    }


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
    ridge_background_sigma = float(
        config.get(
            "laser_ridge_background_sigma_px",
            max(3.0, maximum_width / 2.0),
        )
    )
    minimum_prominence = float(
        config.get(
            "minimum_laser_ridge_prominence",
            max(12.0, delta_threshold * 0.45),
        )
    )
    width_level_fraction = float(
        config.get("laser_ridge_width_level_fraction", 0.5)
    )
    ambiguity_ratio = float(
        config.get("laser_ridge_ambiguity_ratio", 0.75)
    )
    minimum_chromatic_support = float(
        config.get(
            "minimum_laser_ridge_chromatic_support",
            max(6.0, excess_threshold * 0.4),
        )
    )
    fine_sigma = float(config.get("laser_ridge_fine_sigma_px", 2.0))
    minimum_sharpness_ratio = float(
        config.get("minimum_laser_ridge_sharpness_ratio", 0.2)
    )
    reflectance_floor = float(
        config.get("laser_ridge_reflectance_floor", 64.0)
    )
    ridge_thresholds = (
        ridge_background_sigma,
        minimum_prominence,
        width_level_fraction,
        ambiguity_ratio,
        minimum_chromatic_support,
        fine_sigma,
        minimum_sharpness_ratio,
        reflectance_floor,
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
        or ridge_background_sigma <= 0
        or minimum_prominence <= 0
        or not 0 < width_level_fraction < 1
        or not 0 < ambiguity_ratio <= 1
        or minimum_chromatic_support <= 0
        or fine_sigma <= 0
        or fine_sigma >= ridge_background_sigma
        or not 0 < minimum_sharpness_ratio < 1
        or reflectance_floor <= 0
        or not all(math.isfinite(value) for value in ridge_thresholds)
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

    ambient_bgr = ambient[:, :, :3].astype(np.float32)
    laser_bgr = laser[:, :, :3].astype(np.float32)
    channel_delta = laser_bgr - ambient_bgr
    red_delta = channel_delta[:, :, 2]
    laser_excess = laser_bgr[:, :, 2] - np.maximum(
        laser_bgr[:, :, 1], laser_bgr[:, :, 0]
    )
    ambient_excess = ambient_bgr[:, :, 2] - np.maximum(
        ambient_bgr[:, :, 1], ambient_bgr[:, :, 0]
    )
    chromatic_delta = laser_excess - ambient_excess
    raw_candidate_mask = (
        (red_delta >= delta_threshold)
        & (chromatic_delta >= excess_threshold)
        & (roi > 0)
        & (saturated == 0)
    )
    ambient_luminance = ambient_bgr.mean(axis=2)
    reference_luminance = float(np.median(ambient_luminance[roi > 0]))
    reflectance_normalization = np.clip(
        (reference_luminance + reflectance_floor)
        / (ambient_luminance + reflectance_floor),
        0.5,
        2.0,
    )
    normalized_red_delta = red_delta * reflectance_normalization
    normalized_chromatic_delta = chromatic_delta * reflectance_normalization
    response = normalized_red_delta + 0.5 * np.maximum(
        normalized_chromatic_delta,
        0.0,
    )
    background = _gaussian_blur_rows(cv, response, ridge_background_sigma)
    ridge_response = np.maximum(response - background, 0.0)
    fine_background = _gaussian_blur_rows(cv, response, fine_sigma)
    fine_response = np.maximum(response - fine_background, 0.0)
    chromatic_support = _gaussian_blur_rows(
        cv,
        np.maximum(normalized_chromatic_delta, 0.0),
        max(1.0, maximum_width / 4.0),
    )
    ridge_mask = (
        (red_delta >= delta_threshold)
        & (ridge_response >= minimum_prominence)
        & (chromatic_support >= minimum_chromatic_support)
        & (roi > 0)
        & (saturated == 0)
    )
    raw_candidate_pixels = int(np.count_nonzero(raw_candidate_mask))
    diagnostic.update(
        roi_area_px=int(np.count_nonzero(roi)),
        roi_erode_fraction=erode_fraction,
        excluded_ambient_saturated_px=int(
            np.count_nonzero((saturated > 0) & (roi > 0))
        ),
        raw_candidate_pixels=raw_candidate_pixels,
        candidate_pixels=raw_candidate_pixels,
        background_suppressed_ridge_pixels=int(np.count_nonzero(ridge_mask)),
        ridge_background_sigma_px=ridge_background_sigma,
        minimum_ridge_prominence=minimum_prominence,
        minimum_ridge_chromatic_support=minimum_chromatic_support,
        ridge_fine_sigma_px=fine_sigma,
        minimum_ridge_sharpness_ratio=minimum_sharpness_ratio,
        ridge_reflectance_floor=reflectance_floor,
        ridge_reference_luminance=reference_luminance,
    )

    candidates: list[tuple[float, float, float, float, float, float]] = []
    maximum_peaks_per_row = int(config.get("maximum_laser_peaks_per_row", 4))
    if maximum_peaks_per_row <= 0:
        raise CalibrationError("maximum_laser_peaks_per_row must be positive")
    all_peak_prominences: list[float] = []
    all_bilateral_prominences: list[float] = []
    all_peak_widths: list[float] = []
    ambiguous_rows = 0
    rows_with_peaks = 0
    background_suppressed_candidates = 0
    sharpness_ratios: list[float] = []
    shoulder_inner = max(2, int(math.ceil(maximum_width * 0.5)))
    shoulder_outer = max(shoulder_inner + 1, int(math.ceil(maximum_width)))
    for row in range(int(roi_rows.min()), int(roi_rows.max()) + 1, row_stride):
        active = np.flatnonzero(ridge_mask[row])
        if not active.size:
            continue
        split_at = np.flatnonzero(np.diff(active) > 1) + 1
        runs = np.split(active, split_at)
        peaks = []
        for run in runs:
            background_suppressed_candidates += 1
            scores = ridge_response[row, run]
            peak_column = int(run[int(np.argmax(scores))])
            peak_prominence = float(ridge_response[row, peak_column])
            fine_prominence = float(fine_response[row, peak_column])
            sharpness_ratio = fine_prominence / peak_prominence
            if (
                fine_prominence < minimum_prominence * 0.5
                or sharpness_ratio < minimum_sharpness_ratio
            ):
                continue
            left_start = max(0, peak_column - shoulder_outer)
            left_stop = max(0, peak_column - shoulder_inner)
            right_start = min(width, peak_column + shoulder_inner + 1)
            right_stop = min(width, peak_column + shoulder_outer + 1)
            if left_stop <= left_start or right_stop <= right_start:
                continue
            peak_response = float(response[row, peak_column])
            bilateral_prominence = min(
                peak_response
                - float(np.median(response[row, left_start:left_stop])),
                peak_response
                - float(np.median(response[row, right_start:right_stop])),
            )
            if bilateral_prominence < minimum_prominence:
                continue
            level = max(
                minimum_prominence,
                peak_prominence * width_level_fraction,
            )
            left = peak_column
            right = peak_column
            while left > 0 and ridge_response[row, left - 1] >= level:
                left -= 1
            while (
                right + 1 < width
                and ridge_response[row, right + 1] >= level
            ):
                right += 1

            left_crossing = float(left)
            if left > 0:
                inside = float(ridge_response[row, left])
                outside = float(ridge_response[row, left - 1])
                if inside > outside:
                    left_crossing -= (inside - level) / (inside - outside)
            right_crossing = float(right)
            if right + 1 < width:
                inside = float(ridge_response[row, right])
                outside = float(ridge_response[row, right + 1])
                if inside > outside:
                    right_crossing += (inside - level) / (inside - outside)
            local_width = max(right_crossing - left_crossing, 1.0)

            ridge_columns = np.arange(left, right + 1, dtype=float)
            ridge_weights = np.maximum(
                ridge_response[row, left : right + 1] - level,
                1e-3,
            )
            subpixel_column = float(
                np.average(ridge_columns, weights=ridge_weights)
            )
            peaks.append(
                (
                    subpixel_column,
                    float(row),
                    peak_prominence,
                    local_width,
                    bilateral_prominence,
                    sharpness_ratio,
                )
            )
        peaks = sorted(peaks, key=lambda item: item[2], reverse=True)[
            :maximum_peaks_per_row
        ]
        if not peaks:
            continue
        rows_with_peaks += 1
        all_peak_prominences.extend(item[2] for item in peaks)
        all_peak_widths.extend(item[3] for item in peaks)
        all_bilateral_prominences.extend(item[4] for item in peaks)
        sharpness_ratios.extend(item[5] for item in peaks)
        if (
            len(peaks) > 1
            and peaks[1][2] >= peaks[0][2] * ambiguity_ratio
            and abs(peaks[1][0] - peaks[0][0]) > maximum_width
        ):
            ambiguous_rows += 1
            continue
        candidates.extend(peaks)

    diagnostic.update(
        background_suppressed_ridge_candidates=background_suppressed_candidates,
        sharp_ridge_candidates=len(all_peak_prominences),
        rows_with_ridge_peaks=rows_with_peaks,
        ambiguous_rows=ambiguous_rows,
        ambiguity_ratio=ambiguity_ratio,
        median_peak_prominence=(
            float(np.median(all_peak_prominences))
            if all_peak_prominences
            else 0.0
        ),
        p90_peak_prominence=(
            float(np.percentile(all_peak_prominences, 90))
            if all_peak_prominences
            else 0.0
        ),
        median_bilateral_prominence=(
            float(np.median(all_bilateral_prominences))
            if all_bilateral_prominences
            else 0.0
        ),
        median_ridge_sharpness_ratio=(
            float(np.median(sharpness_ratios)) if sharpness_ratios else 0.0
        ),
        median_local_width_px=(
            float(np.median(all_peak_widths)) if all_peak_widths else 0.0
        ),
        p90_local_width_px=(
            float(np.percentile(all_peak_widths, 90))
            if all_peak_widths
            else 0.0
        ),
    )
    if (
        ambiguous_rows >= minimum_rows
        and ambiguous_rows >= math.ceil(rows_with_peaks * 0.5)
    ):
        diagnostic["reason"] = (
            f"laser ridge is ambiguous in {ambiguous_rows} of "
            f"{rows_with_peaks} peak rows"
        )
        return [], diagnostic

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

    initially_selected = best[1]
    selected, coefficients = _robust_ridge_line(
        initially_selected,
        maximum_residual=maximum_residual,
        inlier_tolerance=inlier_tolerance,
        minimum_rows=minimum_rows,
    )
    if len(selected) < minimum_rows:
        diagnostic["reason"] = (
            f"laser ridge retains {len(selected)} rows after robust line fitting; "
            f"{minimum_rows} required"
        )
        return [], diagnostic

    residuals = selected[:, 0] - np.polyval(coefficients, selected[:, 1])
    residual_rms = float(np.sqrt(np.mean(residuals**2)))
    line_rows = np.sort(selected[:, 1])
    line_span = float(np.ptp(line_rows))
    continuity = float(
        len(line_rows) * row_stride / max(line_span + row_stride, row_stride)
    )
    median_width = float(np.median(selected[:, 3]))
    strict_gap_limit = max(
        row_stride * 2.0,
        board_height * maximum_gap_fraction,
    )
    gap_diagnostic = _classify_checker_gaps(
        corner_grid=corner_grid,
        selected=selected,
        coefficients=coefficients,
        row_stride=row_stride,
        strict_gap_limit=strict_gap_limit,
        maximum_residual=maximum_residual,
        maximum_width=maximum_width,
        minimum_prominence=minimum_prominence,
        minimum_chromatic_support=minimum_chromatic_support,
        minimum_sharpness_ratio=minimum_sharpness_ratio,
        ambiguity_ratio=ambiguity_ratio,
        ridge_response=ridge_response,
        fine_response=fine_response,
        chromatic_response=np.maximum(normalized_chromatic_delta, 0.0),
        ambient_luminance=ambient_luminance,
        reference_luminance=reference_luminance,
    )
    selected_row_set = {int(row) for row in selected[:, 1]}
    rejected_rows = np.asarray(
        [row for row in candidate_rows if row not in selected_row_set],
        dtype=float,
    )
    outlier_groups = _contiguous_row_groups(rejected_rows, row_stride)
    diagnostic.update(
        line_rows=int(len(selected)),
        line_span_px=line_span,
        line_span_fraction=line_span / max(board_height, 1.0),
        line_continuity=continuity,
        maximum_row_gap_px=gap_diagnostic["raw_max_gap_px"],
        line_residual_rms_px=residual_rms,
        median_line_width_px=median_width,
        line_slope_x_per_y=float(coefficients[0]),
        line_fit_outlier_rows=int(len(rejected_rows)),
        line_fit_outlier_segments=len(outlier_groups),
        strict_unexplained_gap_limit_px=strict_gap_limit,
        **gap_diagnostic,
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
    if gap_diagnostic["unexplained_max_gap_px"] > strict_gap_limit:
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
    minimum_spread_ratio: float = 1e-3,
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
    spread_ratio = (
        float(singular_values[1] / singular_values[0])
        if len(singular_values) >= 2 and singular_values[0] > 1e-12
        else 0.0
    )
    if (
        len(singular_values) < 2
        or not math.isfinite(minimum_spread_ratio)
        or not 1e-3 <= minimum_spread_ratio < 1
        or spread_ratio < minimum_spread_ratio
    ):
        raise CalibrationError(
            "laser plane points have insufficient 2D conditioning after robust "
            f"rejection (spread ratio {spread_ratio:.3g} < "
            f"{minimum_spread_ratio:.3g})"
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
        "plane_spread_ratio": spread_ratio,
        "minimum_plane_spread_ratio": minimum_spread_ratio,
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

    def finite_at_least(value: Any, minimum: float) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and number >= minimum

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
        if (
            normal.shape != (3,)
            or not np.isfinite(normal).all()
            or not math.isclose(
                float(np.linalg.norm(normal)), 1.0, rel_tol=0, abs_tol=1e-6
            )
        ):
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
            spread_ratio = float(
                quality.get("plane_spread_ratio", math.nan)
            )
            minimum_spread_ratio = float(
                quality.get("minimum_plane_spread_ratio", math.nan)
            )
            minimum_points_per_view = float(
                quality.get("minimum_points_per_view", math.nan)
            )
            minimum_points = float(
                quality.get("minimum_points", math.nan)
            )
            original_poses = float(
                quality.get("original_accepted_poses", math.nan)
            )
            required_retained_poses = float(
                quality.get("required_retained_poses", math.nan)
            )
            retained_pose_fraction = float(
                quality.get("retained_pose_fraction", math.nan)
            )
            minimum_retained_fraction = float(
                quality.get("minimum_retained_pose_fraction", math.nan)
            )
            rejected_pose_fraction = float(
                quality.get("rejected_pose_fraction", math.nan)
            )
            maximum_rejected_fraction = float(
                quality.get("maximum_rejected_pose_fraction", math.nan)
            )
            pose_residual_threshold = float(
                quality.get("pose_residual_threshold_mm", math.nan)
            )
            minimum_pose_inlier_fraction = float(
                quality.get("minimum_pose_inlier_fraction", math.nan)
            )
            hypotheses_evaluated = float(
                quality.get("hypotheses_evaluated", math.nan)
            )
            maximum_hypotheses = float(
                quality.get("maximum_pose_hypotheses", math.nan)
            )
        except (TypeError, ValueError):
            views = minimum_views = orientations = minimum_orientations = math.nan
            spread_ratio = minimum_spread_ratio = minimum_points_per_view = math.nan
            minimum_points = math.nan
            original_poses = required_retained_poses = retained_pose_fraction = math.nan
            minimum_retained_fraction = rejected_pose_fraction = math.nan
            maximum_rejected_fraction = pose_residual_threshold = math.nan
            minimum_pose_inlier_fraction = hypotheses_evaluated = math.nan
            maximum_hypotheses = math.nan
        inlier_points = quality.get("inlier_points_per_pose")
        inlier_points_valid = (
            isinstance(inlier_points, list)
            and math.isfinite(views)
            and math.isfinite(minimum_points_per_view)
            and len(inlier_points) == int(views)
            and len(
                {
                    entry.get("pose_index")
                    for entry in inlier_points
                    if isinstance(entry, Mapping)
                }
            )
            == len(inlier_points)
            and all(
                isinstance(entry, Mapping)
                and finite_at_least(
                    entry.get("points"), minimum_points_per_view
                )
                for entry in inlier_points
            )
        )
        retained_pose_indexes = {
            entry.get("pose_index")
            for entry in inlier_points
            if isinstance(entry, Mapping)
        } if isinstance(inlier_points, list) else set()
        per_pose_residuals = quality.get("per_pose_residuals")
        rejected_poses = quality.get("rejected_poses")
        leave_one_out = quality.get("leave_one_pose_out")
        per_pose_indexes = {
            entry.get("pose_index")
            for entry in per_pose_residuals
            if isinstance(entry, Mapping)
        } if isinstance(per_pose_residuals, list) else set()
        per_pose_retained_indexes = {
            entry.get("pose_index")
            for entry in per_pose_residuals
            if isinstance(entry, Mapping) and entry.get("retained") is True
        } if isinstance(per_pose_residuals, list) else set()
        rejected_pose_indexes = {
            entry.get("pose_index")
            for entry in rejected_poses
            if isinstance(entry, Mapping)
        } if isinstance(rejected_poses, list) else set()
        pose_consensus_valid = (
            quality.get("consensus_method") == "deterministic_pose_balanced_v1"
            and quality.get("ambiguity_checked") is True
            and quality.get("ambiguous") is False
            and all(
                math.isfinite(value)
                for value in (
                    original_poses,
                    required_retained_poses,
                    retained_pose_fraction,
                    minimum_retained_fraction,
                    rejected_pose_fraction,
                    maximum_rejected_fraction,
                    pose_residual_threshold,
                    minimum_pose_inlier_fraction,
                    hypotheses_evaluated,
                    maximum_hypotheses,
                )
            )
            and original_poses >= views >= 3
            and views == int(views)
            and minimum_views == int(minimum_views)
            and orientations == int(orientations)
            and minimum_orientations == int(minimum_orientations)
            and original_poses == int(original_poses)
            and required_retained_poses == int(required_retained_poses)
            and required_retained_poses
            == max(
                minimum_views,
                math.ceil(original_poses * minimum_retained_fraction),
                math.ceil(original_poses * (1.0 - maximum_rejected_fraction)),
            )
            and required_retained_poses <= original_poses
            and views >= required_retained_poses
            and 0.75 <= minimum_retained_fraction <= 1.0
            and math.isclose(
                retained_pose_fraction,
                views / original_poses,
                rel_tol=0,
                abs_tol=1e-9,
            )
            and retained_pose_fraction >= minimum_retained_fraction
            and 0 <= maximum_rejected_fraction <= 0.25
            and math.isclose(
                rejected_pose_fraction,
                (original_poses - views) / original_poses,
                rel_tol=0,
                abs_tol=1e-9,
            )
            and rejected_pose_fraction <= maximum_rejected_fraction
            and 0 < pose_residual_threshold <= 2.0
            and 0.75 <= minimum_pose_inlier_fraction <= 1.0
            and hypotheses_evaluated == int(hypotheses_evaluated)
            and maximum_hypotheses == int(maximum_hypotheses)
            and 1 <= hypotheses_evaluated <= maximum_hypotheses <= 128
            and isinstance(per_pose_residuals, list)
            and len(per_pose_residuals) == int(original_poses)
            and len(per_pose_indexes) == len(per_pose_residuals)
            and per_pose_retained_indexes == retained_pose_indexes
            and all(
                isinstance(entry, Mapping)
                and entry.get("retained") in (True, False)
                and finite_at_least(entry.get("pose_index"), 0)
                and float(entry["pose_index"])
                == int(float(entry["pose_index"]))
                and finite_at_least(entry.get("original_points"), 1)
                and finite_at_least(entry.get("inlier_points"), 0)
                and float(entry["original_points"])
                == int(float(entry["original_points"]))
                and float(entry["inlier_points"])
                == int(float(entry["inlier_points"]))
                and float(entry["inlier_points"])
                <= float(entry["original_points"])
                and finite_at_least(entry.get("inlier_fraction"), 0)
                and float(entry["inlier_fraction"]) <= 1.0
                and math.isclose(
                    float(entry["inlier_fraction"]),
                    float(entry["inlier_points"])
                    / float(entry["original_points"]),
                    rel_tol=0,
                    abs_tol=1e-9,
                )
                and (
                    entry.get("retained") is False
                    or (
                        finite_at_least(
                            entry.get("inlier_points"), minimum_points_per_view
                        )
                        and float(entry["inlier_fraction"])
                        >= minimum_pose_inlier_fraction
                    )
                )
                for entry in per_pose_residuals
            )
            and isinstance(rejected_poses, list)
            and len(rejected_poses) == int(original_poses - views)
            and len(rejected_pose_indexes) == len(rejected_poses)
            and rejected_pose_indexes
            == per_pose_indexes - retained_pose_indexes
            and isinstance(leave_one_out, list)
            and len(leave_one_out) == int(views)
            and {
                entry.get("pose_index")
                for entry in leave_one_out
                if isinstance(entry, Mapping)
            }
            == retained_pose_indexes
        )
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
                    spread_ratio,
                    minimum_spread_ratio,
                    minimum_points,
                    minimum_points_per_view,
                )
            )
            or minimum_views < 3
            or views < minimum_views
            or minimum_orientations < 3
            or orientations < minimum_orientations
            or minimum_spread_ratio < 1e-3
            or spread_ratio < minimum_spread_ratio
            or minimum_points < 30
            or minimum_points_per_view < 10
            or not inlier_points_valid
            or sum(
                int(float(entry["points"]))
                for entry in inlier_points
                if isinstance(entry, Mapping)
                and finite_at_least(entry.get("points"), 0)
            )
            < minimum_points
            or not pose_consensus_valid
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

    def save(
        self, calibration: Mapping[str, Any], report: Mapping[str, Any]
    ) -> dict[str, Any]:
        validate_calibration_payload(calibration)
        current = self._read(missing_ok=True)
        updated = copy.deepcopy(current)
        updated["scan_calibration"] = copy.deepcopy(dict(calibration))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        backup_tmp = self.backup_path.with_suffix(self.backup_path.suffix + ".new")
        config_tmp = self.path.with_suffix(self.path.suffix + ".new")
        report_tmp = self.report_path.with_suffix(self.report_path.suffix + ".new")
        snapshots = {
            destination: destination.read_bytes() if destination.exists() else None
            for destination in (self.path, self.backup_path, self.report_path)
        }
        installed: list[Path] = []
        try:
            self._write_json(backup_tmp, current)
            self._write_json(config_tmp, updated)
            self._write_json(report_tmp, dict(report))
            os.replace(report_tmp, self.report_path)
            installed.append(self.report_path)
            os.replace(backup_tmp, self.backup_path)
            installed.append(self.backup_path)
            self._fsync_directory(self.path.parent)
            os.replace(config_tmp, self.path)
            installed.append(self.path)
            self._fsync_directory(self.path.parent)
        except Exception as exc:
            try:
                self._restore_snapshots(snapshots, installed)
            except Exception as restore_error:
                raise CalibrationError(
                    "calibration persistence failed and durable rollback also "
                    f"failed: {restore_error}"
                ) from exc
            raise
        finally:
            for temporary in (
                backup_tmp,
                config_tmp,
                report_tmp,
                self.path.with_suffix(self.path.suffix + ".restore"),
                self.backup_path.with_suffix(self.backup_path.suffix + ".restore"),
                self.report_path.with_suffix(self.report_path.suffix + ".restore"),
            ):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
        return {
            "snapshots": snapshots,
            "previous_calibration": copy.deepcopy(
                current.get("scan_calibration", {})
            ),
        }

    def restore(self, transaction: Mapping[str, Any]) -> dict:
        snapshots = transaction.get("snapshots")
        if not isinstance(snapshots, Mapping):
            raise CalibrationError("calibration transaction snapshot is invalid")
        expected = (self.path, self.backup_path, self.report_path)
        if set(snapshots) != set(expected):
            raise CalibrationError("calibration transaction snapshot is incomplete")
        self._restore_snapshots(snapshots, list(expected))
        return copy.deepcopy(dict(transaction.get("previous_calibration", {})))

    def rollback(self) -> dict:
        if not self.backup_path.exists():
            raise CalibrationError("no calibration backup is available")
        backup = self._read(self.backup_path)
        temporary = self.path.with_suffix(self.path.suffix + ".rollback")
        snapshot = {
            self.path: self.path.read_bytes() if self.path.exists() else None
        }
        try:
            self._write_json(temporary, backup)
            os.replace(temporary, self.path)
            self._fsync_directory(self.path.parent)
        except Exception as exc:
            try:
                self._restore_snapshots(snapshot, [self.path])
            except Exception as restore_error:
                raise CalibrationError(
                    "calibration rollback failed and previous active config "
                    f"could not be restored: {restore_error}"
                ) from exc
            raise
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

    def _restore_snapshots(
        self,
        snapshots: Mapping[Path, bytes | None],
        destinations: list[Path],
    ) -> None:
        restore_errors = []
        sidecars = [
            destination
            for destination in (self.report_path, self.backup_path)
            if destination in destinations
        ]

        def restore_one(destination: Path) -> None:
            previous = snapshots[destination]
            try:
                if previous is None:
                    try:
                        destination.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    restore_tmp = destination.with_suffix(
                        destination.suffix + ".restore"
                    )
                    self._write_bytes(restore_tmp, previous)
                    os.replace(restore_tmp, destination)
            except Exception as exc:
                restore_errors.append(f"{destination.name}: {exc}")

        for destination in sidecars:
            restore_one(destination)
        if sidecars:
            try:
                self._fsync_directory(self.path.parent)
            except Exception as exc:
                restore_errors.append(f"sidecar directory: {exc}")
        if self.path in destinations:
            restore_one(self.path)
            try:
                self._fsync_directory(self.path.parent)
            except Exception as exc:
                restore_errors.append(f"active-config directory: {exc}")
        if restore_errors:
            raise CalibrationError(
                "failed to restore calibration transaction ("
                + "; ".join(restore_errors)
                + ")"
            )

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_file = kernel32.CreateFileW
            create_file.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            create_file.restype = wintypes.HANDLE
            flush_file_buffers = kernel32.FlushFileBuffers
            flush_file_buffers.argtypes = [wintypes.HANDLE]
            flush_file_buffers.restype = wintypes.BOOL
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            handle = create_file(
                str(path),
                0x40000000,
                0x00000001 | 0x00000002 | 0x00000004,
                None,
                3,
                0x02000000,
                None,
            )
            if handle == ctypes.c_void_p(-1).value:
                error = ctypes.get_last_error()
                raise CalibrationError(
                    f"failed to open calibration directory {path} for flush "
                    f"(Windows error {error})"
                )
            try:
                if not flush_file_buffers(handle):
                    error = ctypes.get_last_error()
                    raise CalibrationError(
                        f"failed to flush calibration directory {path} "
                        f"(Windows error {error})"
                    )
            finally:
                close_handle(handle)
            return
        flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0))
        try:
            descriptor = os.open(str(path), flags)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise CalibrationError(
                f"failed to fsync calibration directory {path}: {exc}"
            ) from exc


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
        get_current_calibration: Callable[[], Mapping[str, Any]] | None = None,
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
        self._get_current_calibration = get_current_calibration
        self._cv = cv_module if cv_module is not None else _cv2
        self._sleep = sleep
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False
        self._commit_in_progress = False
        self._cancel_after_commit = False
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
            elif name == "pi" and not callable(
                getattr(camera, "matched_photometric_controls", None)
            ):
                blockers.append(
                    "Pi Camera cannot guarantee matched ambient/laser photometry"
                )
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
                    if name == "pi":
                        support_probe = getattr(
                            camera,
                            "matched_photometric_controls_supported",
                            None,
                        )
                        if callable(support_probe):
                            supported, missing = support_probe()
                            if not supported:
                                raise CalibrationError(
                                    "matched photometric controls unavailable: "
                                    + ", ".join(missing)
                                )
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
            self._commit_in_progress = False
            self._cancel_after_commit = False
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
            if self._active and self._commit_in_progress:
                self._cancel_after_commit = True
                self._status["step"] = (
                    "Finishing atomic calibration activation before stopping"
                )
            else:
                self._cancel.set()
            if self._active and not self._commit_in_progress:
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
            if start_positions is not None:
                self._move_to(start_positions)
            self._begin_commit()
            self._save_and_activate(calibration, report)
            self._finish_commit(report)
        except CalibrationCancelled:
            self._set_error("cancelled", "Calibration cancelled")
            self._report = self._failure_report("Calibration cancelled")
        except Exception as exc:
            self._set_error("error", str(exc))
            self._report = self._failure_report(str(exc))
        finally:
            self._safe_outputs()
            with self._lock:
                self._commit_in_progress = False
                self._active = False
                self._status["active"] = False
            self._reservation.release()

    def _begin_commit(self) -> None:
        with self._lock:
            self._check_cancelled()
            self._commit_in_progress = True
            self._status.update(
                phase="persisting",
                step="Writing and activating atomic calibration",
                progress=97.0,
            )

    def _finish_commit(self, report: Mapping[str, Any]) -> bool:
        with self._lock:
            late_cancellation = self._cancel_after_commit
            self._cancel_after_commit = False
            if late_cancellation:
                self._cancel.set()
            self._report = copy.deepcopy(dict(report))
            self._status.update(
                active=False,
                phase="complete",
                step=(
                    "Calibration saved; cancellation arrived during activation"
                    if late_cancellation
                    else "Calibration saved"
                ),
                progress=100.0,
            )
            self._active = False
            self._commit_in_progress = False
            return late_cancellation

    def _save_and_activate(
        self,
        calibration: Mapping[str, Any],
        report: Mapping[str, Any],
    ) -> None:
        previous_runtime = None
        if self._get_current_calibration is not None:
            previous_runtime = copy.deepcopy(
                dict(self._get_current_calibration())
            )
        transaction = self._store.save(calibration, report)
        if self._on_saved is None:
            return
        try:
            self._on_saved(calibration)
        except Exception as activation_error:
            previous_disk = copy.deepcopy(
                transaction.get("previous_calibration", {})
            )
            if previous_runtime is None:
                previous_runtime = copy.deepcopy(previous_disk)
            rollback_errors = []
            try:
                self._store.restore(transaction)
            except Exception as exc:
                rollback_errors.append(f"persistent state: {exc}")
            try:
                self._on_saved(previous_runtime)
            except Exception as exc:
                rollback_errors.append(f"runtime state: {exc}")
            detail = (
                "; rollback failures: " + "; ".join(rollback_errors)
                if rollback_errors
                else "; previous persistent and runtime calibration restored"
            )
            raise CalibrationError(
                f"calibration runtime activation failed: {activation_error}{detail}"
            ) from activation_error

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
                {"x": 0, "y": 0, "z": 20},
                {"x": -10, "y": 10.4719755, "z": 10},
                {"x": -20, "y": 20.9439510, "z": 20},
                {"x": -20, "y": 20.9439510, "z": 0},
                {"x": -30, "y": 31.4159265, "z": 10},
                {"x": 0, "y": 41.8879020, "z": 0},
                {"x": 0, "y": 41.8879020, "z": 20},
                {"x": -30, "y": 52.3598776, "z": 10},
                {"x": -15, "y": 62.8318531, "z": 20},
                {"x": -15, "y": 62.8318531, "z": 0},
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
        trajectory_deltas = np.asarray(
            [
                [
                    float(pose[axis]) - float(poses[0][axis])
                    for axis in ("x", "y", "z")
                ]
                for pose in poses
            ],
            dtype=float,
        )
        minimum_z_leverage = float(
            self._config.get("minimum_carriage_z_leverage_ratio", 0.25)
        )
        if (
            not math.isfinite(minimum_z_leverage)
            or not 0 < minimum_z_leverage <= 1
        ):
            raise CalibrationError(
                "minimum_carriage_z_leverage_ratio must be in (0, 1]"
            )
        try:
            leverage = self._independent_z_leverage_metrics(
                trajectory_deltas
            )
        except CalibrationError as exc:
            raise CalibrationError(
                "calibration trajectory must keep commanded X, Y, and Z "
                "independently observable"
            ) from exc
        if leverage["ratio"] < minimum_z_leverage:
            raise CalibrationError(
                "calibration trajectory has insufficient independent Z leverage "
                f"after commanded X/Y residualization "
                f"({leverage['ratio']:.3f} < {minimum_z_leverage:.3f})"
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
                    "detection_method": view.get("detection_method"),
                    "glare_masked": bool(view.get("glare_masked")),
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
        required_z_levels = sorted(
            {
                round(float(view["pose"]["z"]), 6)
                for view in views
                if "pose" in view and "z" in view["pose"]
            }
        )
        fits: dict[str, dict[str, Any]] = {}
        for adjustment_name, adjustment in adjustments.items():
            if not math.isclose(
                float(np.linalg.det(adjustment)), 1.0, rel_tol=0, abs_tol=1e-9
            ):
                raise CalibrationError(
                    f"{name} PnP board-frame adjustment would reflect handedness"
                )
            (
                raw_candidates,
                candidate_views,
                candidate_view_numbers,
                normalization,
            ) = self._normalized_pnp_candidates(
                name,
                views,
                base_adjustment=adjustment_name,
            )
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
                        required_z_levels=required_z_levels,
                        view_numbers=candidate_view_numbers,
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
                        "pnp_board_frame_normalization": normalization,
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
            for residual, view_number in zip(
                candidate_residuals, candidate_view_numbers
            ):
                residual["view"] = view_number
            inliers = sum(item["inlier"] for item in candidate_residuals)
            if name == "usb" and carriage_fit is not None:
                pnp_inliers = np.asarray(
                    [residual["inlier"] for residual in candidate_residuals],
                    dtype=bool,
                )
                if not bool(pnp_inliers.all()) and int(pnp_inliers.sum()) >= minimum:
                    try:
                        refit = self._fit_usb_carriage(
                            candidate_views,
                            raw_candidates,
                            minimum=minimum,
                            eligible=pnp_inliers,
                            required_z_levels=required_z_levels,
                            view_numbers=candidate_view_numbers,
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
                        for residual, view_number in zip(
                            candidate_residuals, candidate_view_numbers
                        ):
                            residual["view"] = view_number
                        inliers = sum(
                            item["inlier"] for item in candidate_residuals
                        )
                elif int(pnp_inliers.sum()) < minimum:
                    carriage_fit["accepted"] = False
                    carriage_fit["refit_error"] = (
                        "USB carriage refit has insufficient robust PnP inliers"
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
                "pnp_board_frame_normalization": normalization,
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
        selected_normalization = selected_fit["pnp_board_frame_normalization"]
        with self._lock:
            residual_index = 0
            for diagnostic in self._status["pnp_views"][name]:
                if diagnostic.get("pnp_valid"):
                    diagnostic["extrinsic_candidate"] = copy.deepcopy(
                        candidate_residuals[residual_index]
                    )
                    convention = selected_normalization["per_view"][residual_index]
                    diagnostic["board_frame_adjustment"] = convention[
                        "selected_adjustment"
                    ]
                    diagnostic["board_frame_adjustment_changed"] = convention[
                        "changed"
                    ]
                    diagnostic[
                        "board_frame_rotation_candidate_residuals_deg"
                    ] = copy.deepcopy(convention["rotation_residuals_deg"])
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
            pnp_board_frame_normalization=copy.deepcopy(selected_normalization),
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

    def _normalized_pnp_candidates(
        self,
        name: str,
        views: list[dict],
        *,
        base_adjustment: str,
    ) -> tuple[list[np.ndarray], list[dict], list[int], dict[str, Any]]:
        adjustment_options = (
            {"identity": PNP_BOARD_FRAME_ADJUSTMENTS["identity"]}
            if name == "pi"
            else PNP_BOARD_FRAME_ADJUSTMENTS
        )
        variants_by_view: list[dict[str, np.ndarray]] = []
        candidate_views = []
        candidate_view_numbers = []
        for view_number, view in enumerate(views, start=1):
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
            scanner_from_board = self._board_to_scanner(view["pose"])
            variants = {}
            for adjustment_name, adjustment in adjustment_options.items():
                adjusted = observed.copy()
                # The board origin is centered, so a proper discrete frame rotation
                # changes only its basis and never manufactures a translation.
                adjusted[:3, :3] = observed_rotation @ adjustment
                variants[adjustment_name] = (
                    scanner_from_board @ np.linalg.inv(adjusted)
                )
            variants_by_view.append(variants)
            candidate_views.append(view)
            candidate_view_numbers.append(view_number)

        baseline = [
            variants[base_adjustment] for variants in variants_by_view
        ]
        rotation_only = []
        for candidate in baseline:
            transform = np.eye(4)
            transform[:3, :3] = candidate[:3, :3]
            rotation_only.append(transform)
        if rotation_only:
            rotation_reference = self._robust_average_transforms(rotation_only)[
                0
            ][:3, :3]
        else:
            rotation_reference = np.eye(3)

        candidates = []
        per_view = []
        changed_views = []
        for view_number, variants in zip(candidate_view_numbers, variants_by_view):
            rotation_residuals = {
                adjustment_name: self._rotation_residual_deg(
                    rotation_reference, candidate[:3, :3]
                )
                for adjustment_name, candidate in variants.items()
            }
            selected_adjustment = min(
                rotation_residuals,
                key=lambda adjustment_name: (
                    rotation_residuals[adjustment_name],
                    adjustment_name,
                ),
            )
            changed = selected_adjustment != base_adjustment
            if changed:
                changed_views.append(view_number)
            candidates.append(variants[selected_adjustment])
            per_view.append(
                {
                    "view": view_number,
                    "base_adjustment": base_adjustment,
                    "selected_adjustment": selected_adjustment,
                    "changed": changed,
                    "selected_rotation_residual_deg": round(
                        rotation_residuals[selected_adjustment], 5
                    ),
                    "rotation_residuals_deg": {
                        adjustment_name: round(residual, 5)
                        for adjustment_name, residual in rotation_residuals.items()
                    },
                }
            )
        return (
            candidates,
            candidate_views,
            candidate_view_numbers,
            {
                "base_adjustment": base_adjustment,
                "changed_views": changed_views,
                "changed_view_count": len(changed_views),
                "per_view": per_view,
            },
        )

    def _fit_usb_carriage(
        self,
        views: list[dict],
        candidates: list[np.ndarray],
        *,
        minimum: int,
        eligible: np.ndarray | None = None,
        required_z_levels: list[float] | None = None,
        view_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        regression = self._robust_translation_regression(
            views,
            candidates,
            minimum=minimum,
            eligible=eligible,
            required_z_levels=required_z_levels,
            view_numbers=view_numbers,
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
        maximum_uncertainty = float(
            self._config.get(
                "maximum_usb_z_vector_uncertainty_mm_per_commanded_mm",
                0.15,
            )
        )
        if not all(
            math.isfinite(value) and value > 0
            for value in (
                scale_tolerance,
                maximum_vertical_alignment,
                maximum_condition,
                maximum_uncertainty,
            )
        ):
            raise CalibrationError(
                "USB carriage fit tolerances must be finite and positive"
            )
        maximum_repeatability = float(
            self._config.get("maximum_extrinsic_rms_mm", 5.0)
        )
        maximum_level_repeatability = max(
            (
                float(level["repeatability_rms_mm"])
                for level in regression["z_level_support"]
            ),
            default=math.inf,
        )
        accepted = (
            regression["observable"]
            and int(regression["inlier_mask"].sum()) >= minimum
            and abs(scale - 1.0) <= scale_tolerance
            and vertical_alignment <= maximum_vertical_alignment
            and regression["design_condition_number"] <= maximum_condition
            and regression["residual_rms_mm"] <= maximum_repeatability
            and maximum_level_repeatability <= maximum_repeatability
            and regression["vector_uncertainty_mm_per_commanded_mm"]
            <= maximum_uncertainty
        )
        return {
            "accepted": bool(accepted),
            "estimator": regression["estimator"],
            "commanded_xy_model_source": "fixed_pi_axis_model",
            "pi_x_mm_per_commanded_mm": float(
                self._motion_model["x_mm_per_commanded_mm"]
            ),
            "pi_y_radians_per_commanded_mm": float(
                self._motion_model["y_radians_per_commanded_mm"]
            ),
            "vector_mm_per_commanded_mm": vector.tolist(),
            "scale_mm_per_commanded_mm": scale,
            "signed_vertical_scale_mm_per_commanded_mm": float(vector[2]),
            "vertical_alignment_deg": vertical_alignment,
            "maximum_vertical_alignment_deg": maximum_vertical_alignment,
            "scale_tolerance_fraction": scale_tolerance,
            "design_condition_number": regression["design_condition_number"],
            "maximum_design_condition_number": maximum_condition,
            "independent_z_leverage_ratio": regression[
                "independent_z_leverage_ratio"
            ],
            "minimum_independent_z_leverage_ratio": regression[
                "minimum_independent_z_leverage_ratio"
            ],
            "independent_z_leverage_rms_mm": regression[
                "independent_z_leverage_rms_mm"
            ],
            "independent_z_leverage_span_mm": regression[
                "independent_z_leverage_span_mm"
            ],
            "maximum_independent_z_leverage_fraction": regression[
                "maximum_independent_z_leverage_fraction"
            ],
            "independent_z_effective_samples": regression[
                "independent_z_effective_samples"
            ],
            "z_span_mm": regression["z_span_mm"],
            "z_levels": regression["z_levels"],
            "z_level_samples": regression["z_level_samples"],
            "z_level_inliers": regression["z_level_inliers"],
            "z_level_support": regression["z_level_support"],
            "regression_residual_rms_mm": regression["residual_rms_mm"],
            "maximum_regression_residual_rms_mm": maximum_repeatability,
            "maximum_z_level_repeatability_mm": maximum_repeatability,
            "vector_uncertainty_mm_per_commanded_mm": regression[
                "vector_uncertainty_mm_per_commanded_mm"
            ],
            "maximum_vector_uncertainty_mm_per_commanded_mm": maximum_uncertainty,
            "jackknife_fits": regression["jackknife_fits"],
            "direct_same_xy_z_contrasts": regression[
                "direct_same_xy_z_contrasts"
            ],
            "regression_rejected_views": regression["rejected_views"],
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
        required_z_levels: list[float] | None = None,
        view_numbers: list[int] | None = None,
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
        if allowed.shape != (len(views),):
            raise CalibrationError("translation regression eligibility mask is invalid")
        reported_view_numbers = (
            list(range(1, len(views) + 1))
            if view_numbers is None
            else [int(view_number) for view_number in view_numbers]
        )
        if len(reported_view_numbers) != len(views):
            raise CalibrationError(
                "translation regression view-number mapping is invalid"
            )
        allowed_indexes = np.flatnonzero(allowed)
        all_levels = np.asarray(
            [round(float(view["pose"]["z"]), 6) for view in views],
            dtype=float,
        )
        required_levels = sorted(
            {
                round(float(level), 6)
                for level in (
                    required_z_levels
                    if required_z_levels is not None
                    else all_levels.tolist()
                )
            }
        )
        available_levels = set(all_levels.tolist())
        for level in required_levels:
            if level not in available_levels:
                raise CalibrationError(
                    "USB carriage PnP views remove all support for "
                    f"Z={level:g}mm"
                )
            if not bool(np.any(allowed & np.isclose(all_levels, level, atol=1e-6))):
                raise CalibrationError(
                    "USB carriage robust PnP mask removes all support for "
                    f"Z={level:g}mm"
                )
        if len(allowed_indexes) < minimum:
            raise CalibrationError(
                "USB carriage motion is not observable from enough PnP views"
            )
        if len(required_levels) < 3:
            raise CalibrationError(
                "USB carriage motion requires at least three commanded Z levels"
            )
        z_span = float(max(required_levels) - min(required_levels))
        if z_span < 20.0 - 1e-6:
            raise CalibrationError(
                "USB carriage motion requires commanded Z levels spanning 20mm"
            )

        minimum_leverage = float(
            self._config.get("minimum_carriage_z_leverage_ratio", 0.25)
        )
        maximum_residual = float(
            self._config.get("maximum_extrinsic_rms_mm", 5.0)
        )
        if (
            not math.isfinite(minimum_leverage)
            or not 0 < minimum_leverage <= 1
            or not math.isfinite(maximum_residual)
            or maximum_residual <= 0
        ):
            raise CalibrationError(
                "USB carriage leverage and residual thresholds are invalid"
            )

        inlier_mask = allowed.copy()
        while True:
            solution = self._translation_regression_solution(
                deltas, translations, inlier_mask
            )
            if (
                not solution["observable"]
                or solution["independent_z_leverage_ratio"] < minimum_leverage
            ):
                raise CalibrationError(
                    "USB carriage motion has insufficient independent Z leverage "
                    "after residualizing commanded X/Y"
                )
            residuals = np.linalg.norm(
                translations - design @ solution["coefficients"], axis=1
            )
            residual_rms = float(
                np.sqrt(np.mean(np.square(residuals[inlier_mask])))
            )
            if residual_rms <= maximum_residual:
                break

            best_trial = None
            for index in np.flatnonzero(inlier_mask):
                level = all_levels[index]
                if (
                    int(
                        np.count_nonzero(
                            inlier_mask
                            & np.isclose(all_levels, level, atol=1e-6)
                        )
                    )
                    <= 1
                    or int(inlier_mask.sum()) - 1 < minimum
                ):
                    continue
                trial = inlier_mask.copy()
                trial[index] = False
                try:
                    trial_solution = self._translation_regression_solution(
                        deltas, translations, trial
                    )
                except CalibrationError:
                    continue
                if (
                    not trial_solution["observable"]
                    or trial_solution["independent_z_leverage_ratio"]
                    < minimum_leverage
                ):
                    continue
                trial_residuals = np.linalg.norm(
                    translations - design @ trial_solution["coefficients"],
                    axis=1,
                )
                trial_rms = float(
                    np.sqrt(np.mean(np.square(trial_residuals[trial])))
                )
                key = (trial_rms, int(index))
                if best_trial is None or key < best_trial[0]:
                    best_trial = (key, trial)
            if best_trial is None or best_trial[0][0] >= residual_rms - 1e-9:
                break
            inlier_mask = best_trial[1]

        solution = self._translation_regression_solution(
            deltas, translations, inlier_mask
        )
        coefficients = np.asarray(solution["coefficients"], dtype=float)
        all_residuals = np.linalg.norm(
            translations - design @ coefficients, axis=1
        )
        residual_rms = float(
            np.sqrt(np.mean(np.square(all_residuals[inlier_mask])))
        )
        z_level_support = []
        z_level_samples = {}
        z_level_inliers = {}
        for level in required_levels:
            level_mask = np.isclose(all_levels, level, atol=1e-6)
            level_inliers = level_mask & inlier_mask
            label = f"{level:g}"
            samples = int(np.count_nonzero(level_mask))
            inliers = int(np.count_nonzero(level_inliers))
            if inliers == 0:
                raise CalibrationError(
                    "USB carriage robust rejection would remove all support for "
                    f"Z={level:g}mm"
                )
            repeatability = float(
                np.sqrt(np.mean(np.square(all_residuals[level_inliers])))
            )
            z_level_samples[label] = samples
            z_level_inliers[label] = inliers
            z_level_support.append(
                {
                    "z_mm": level,
                    "samples": samples,
                    "eligible": int(np.count_nonzero(level_mask & allowed)),
                    "inliers": inliers,
                    "repeatability_rms_mm": repeatability,
                    "maximum_residual_mm": float(
                        np.max(all_residuals[level_inliers])
                    ),
                }
            )

        selected_indexes = np.flatnonzero(inlier_mask)
        direct_contrasts = self._direct_z_contrasts(
            deltas, translations, selected_indexes
        )
        if direct_contrasts:
            direct_array = np.asarray(
                [contrast["vector"] for contrast in direct_contrasts],
                dtype=float,
            )
            direct_vector = self._geometric_median(direct_array)
            direct_spread = float(
                np.max(np.linalg.norm(direct_array - direct_vector, axis=1))
            )
            pairwise_spread = max(
                (
                    float(np.linalg.norm(direct_array[first] - direct_array[second]))
                    for first in range(len(direct_array))
                    for second in range(first + 1, len(direct_array))
                ),
                default=0.0,
            )
            direct_diagnostics = {
                "method": "widest_same_xy_z_contrast_geometric_median",
                "pairs": len(direct_contrasts),
                "median_vector_mm_per_commanded_mm": direct_vector.tolist(),
                "maximum_vector_deviation_mm_per_commanded_mm": direct_spread,
                "maximum_pairwise_vector_difference_mm_per_commanded_mm": (
                    pairwise_spread
                ),
                "contrasts": [
                    {
                        "first_view": reported_view_numbers[
                            contrast["first_index"]
                        ],
                        "second_view": reported_view_numbers[
                            contrast["second_index"]
                        ],
                        "delta_z_mm": contrast["delta_z_mm"],
                        "vector_mm_per_commanded_mm": contrast["vector"].tolist(),
                    }
                    for contrast in direct_contrasts
                ],
            }
        else:
            direct_diagnostics = {
                "method": "widest_same_xy_z_contrast_geometric_median",
                "pairs": 0,
                "median_vector_mm_per_commanded_mm": None,
                "maximum_vector_deviation_mm_per_commanded_mm": None,
                "maximum_pairwise_vector_difference_mm_per_commanded_mm": None,
                "contrasts": [],
            }

        vector = np.asarray(coefficients[3], dtype=float)
        estimator = solution["estimator"]
        jackknife_deviations = []
        jackknife_fits = 0
        for index in selected_indexes:
            level = all_levels[index]
            if (
                int(
                    np.count_nonzero(
                        inlier_mask & np.isclose(all_levels, level, atol=1e-6)
                    )
                )
                <= 1
                or int(inlier_mask.sum()) - 1 < 4
            ):
                continue
            trial = inlier_mask.copy()
            trial[index] = False
            try:
                trial_solution = self._translation_regression_solution(
                    deltas,
                    translations,
                    trial,
                    estimator=estimator,
                )
            except CalibrationError:
                continue
            if trial_solution["observable"]:
                jackknife_deviations.append(
                    float(
                        np.linalg.norm(
                            np.asarray(
                                trial_solution["coefficients"][3], dtype=float
                            )
                            - vector
                        )
                    )
                )
                jackknife_fits += 1

        if estimator == RESIDUALIZED_Z_ESTIMATOR:
            for level in required_levels:
                trial = inlier_mask & ~np.isclose(all_levels, level, atol=1e-6)
                if int(trial.sum()) < 4:
                    continue
                try:
                    trial_solution = self._translation_regression_solution(
                        deltas,
                        translations,
                        trial,
                        estimator=RESIDUALIZED_Z_ESTIMATOR,
                    )
                except CalibrationError:
                    continue
                if trial_solution["observable"]:
                    jackknife_deviations.append(
                        float(
                            np.linalg.norm(
                                np.asarray(
                                    trial_solution["coefficients"][3],
                                    dtype=float,
                                )
                                - vector
                            )
                        )
                    )
                    jackknife_fits += 1

        if estimator == DIRECT_Z_ESTIMATOR:
            # Endpoint Z levels are not independent units: deleting one destroys
            # every contrast. Delete complete X/Y contrast groups instead.
            for contrast in direct_contrasts:
                trial = inlier_mask.copy()
                trial[contrast["first_index"]] = False
                trial[contrast["second_index"]] = False
                if int(trial.sum()) < 4:
                    continue
                try:
                    trial_solution = self._translation_regression_solution(
                        deltas,
                        translations,
                        trial,
                        estimator=DIRECT_Z_ESTIMATOR,
                    )
                except CalibrationError:
                    continue
                if trial_solution["observable"]:
                    jackknife_deviations.append(
                        float(
                            np.linalg.norm(
                                np.asarray(
                                    trial_solution["coefficients"][3], dtype=float
                                )
                                - vector
                            )
                        )
                    )
                    jackknife_fits += 1

        jackknife_uncertainty = max(jackknife_deviations, default=0.0)
        direct_uncertainty = (
            float(
                direct_diagnostics[
                    "maximum_pairwise_vector_difference_mm_per_commanded_mm"
                ]
            )
            if len(direct_contrasts) >= MINIMUM_DIRECT_Z_CONTRASTS
            else 0.0
        )
        uncertainty = max(jackknife_uncertainty, direct_uncertainty)
        return {
            "coefficients": coefficients,
            "inlier_mask": inlier_mask,
            "estimator": estimator,
            "design_condition_number": solution["design_condition_number"],
            "observable": bool(
                solution["observable"]
                and solution["independent_z_leverage_ratio"] >= minimum_leverage
            ),
            "independent_z_leverage_ratio": solution[
                "independent_z_leverage_ratio"
            ],
            "minimum_independent_z_leverage_ratio": minimum_leverage,
            "independent_z_leverage_rms_mm": solution[
                "independent_z_leverage_rms_mm"
            ],
            "independent_z_leverage_span_mm": solution[
                "independent_z_leverage_span_mm"
            ],
            "maximum_independent_z_leverage_fraction": solution[
                "maximum_independent_z_leverage_fraction"
            ],
            "independent_z_effective_samples": solution[
                "independent_z_effective_samples"
            ],
            "z_span_mm": z_span,
            "z_levels": required_levels,
            "z_level_samples": z_level_samples,
            "z_level_inliers": z_level_inliers,
            "z_level_support": z_level_support,
            "residual_rms_mm": residual_rms,
            "rejected_views": [
                reported_view_numbers[index]
                for index in np.flatnonzero(allowed & ~inlier_mask)
            ],
            "direct_same_xy_z_contrasts": direct_diagnostics,
            "vector_uncertainty_mm_per_commanded_mm": uncertainty,
            "jackknife_fits": jackknife_fits,
        }

    @staticmethod
    def _translation_regression_solution(
        deltas: np.ndarray,
        translations: np.ndarray,
        selected: np.ndarray,
        *,
        estimator: str | None = None,
    ) -> dict[str, Any]:
        selected_deltas = np.asarray(deltas[selected], dtype=float)
        selected_translations = np.asarray(translations[selected], dtype=float)
        if len(selected_deltas) < 4:
            raise CalibrationError(
                "USB carriage motion is not observable from enough PnP views"
            )
        leverage = GeometricCalibrationService._independent_z_leverage_metrics(
            selected_deltas
        )
        nuisance = np.column_stack(
            (
                np.ones(len(selected_deltas)),
                selected_deltas[:, 0],
                selected_deltas[:, 1],
            )
        )
        commanded_z = selected_deltas[:, 2]
        residualized_z = leverage["residualized_z"]
        residualized_energy = leverage["residualized_energy"]
        direct_contrasts = GeometricCalibrationService._direct_z_contrasts(
            selected_deltas,
            selected_translations,
            np.arange(len(selected_deltas)),
        )
        if estimator not in (
            None,
            DIRECT_Z_ESTIMATOR,
            RESIDUALIZED_Z_ESTIMATOR,
        ):
            raise CalibrationError("USB carriage estimator selection is invalid")
        use_direct = estimator == DIRECT_Z_ESTIMATOR or (
            estimator is None
            and len(direct_contrasts) >= MINIMUM_DIRECT_Z_CONTRASTS
        )
        if use_direct:
            if not direct_contrasts:
                raise CalibrationError(
                    "USB carriage direct estimator has no same-X/Y Z contrasts"
                )
            vector = GeometricCalibrationService._geometric_median(
                np.asarray(
                    [contrast["vector"] for contrast in direct_contrasts],
                    dtype=float,
                )
            )
            selected_estimator = DIRECT_Z_ESTIMATOR
        else:
            nuisance_translation = nuisance @ np.linalg.lstsq(
                nuisance, selected_translations, rcond=None
            )[0]
            residualized_translation = selected_translations - nuisance_translation
            vector = (
                residualized_z @ residualized_translation
            ) / residualized_energy
            selected_estimator = RESIDUALIZED_Z_ESTIMATOR
        nuisance_coefficients = np.linalg.lstsq(
            nuisance,
            selected_translations - commanded_z[:, None] * vector,
            rcond=None,
        )[0]
        coefficients = np.vstack((nuisance_coefficients, vector))
        design = np.column_stack(
            (np.ones(len(selected_deltas)), selected_deltas)
        )
        rank = int(np.linalg.matrix_rank(design))
        feature_spread = np.std(selected_deltas, axis=0)
        if bool(np.any(feature_spread <= 1e-9)):
            condition = math.inf
        else:
            standardized = (
                selected_deltas - np.mean(selected_deltas, axis=0)
            ) / feature_spread
            condition = float(
                np.linalg.cond(
                    np.column_stack(
                        (np.ones(len(selected_deltas)), standardized)
                    )
                )
            )
        return {
            "coefficients": coefficients,
            "estimator": selected_estimator,
            "design_condition_number": condition,
            "observable": rank == 4 and math.isfinite(condition),
            "independent_z_leverage_ratio": leverage["ratio"],
            "independent_z_leverage_rms_mm": leverage["rms_mm"],
            "independent_z_leverage_span_mm": leverage["span_mm"],
            "maximum_independent_z_leverage_fraction": leverage[
                "maximum_fraction"
            ],
            "independent_z_effective_samples": leverage["effective_samples"],
        }

    @staticmethod
    def _direct_z_contrasts(
        deltas: np.ndarray,
        translations: np.ndarray,
        selected_indexes: np.ndarray,
    ) -> list[dict[str, Any]]:
        groups: dict[tuple[float, float], list[int]] = {}
        for index in np.asarray(selected_indexes, dtype=int):
            key = (
                round(float(deltas[index, 0]), 6),
                round(float(deltas[index, 1]), 6),
            )
            groups.setdefault(key, []).append(int(index))

        contrasts = []
        for indexes in groups.values():
            ordered = sorted(indexes, key=lambda index: float(deltas[index, 2]))
            first, second = ordered[0], ordered[-1]
            delta_z = float(deltas[second, 2] - deltas[first, 2])
            if abs(delta_z) <= 1e-6:
                continue
            contrasts.append(
                {
                    "first_index": first,
                    "second_index": second,
                    "delta_z_mm": delta_z,
                    "vector": (
                        translations[second] - translations[first]
                    )
                    / delta_z,
                }
            )
        return contrasts

    @staticmethod
    def _geometric_median(values: np.ndarray) -> np.ndarray:
        points = np.asarray(values, dtype=float)
        if points.ndim != 2 or not len(points):
            raise CalibrationError("geometric median requires vector samples")
        estimate = np.mean(points, axis=0)
        for _ in range(100):
            distances = np.linalg.norm(points - estimate, axis=1)
            noncoincident = distances > 1e-12
            if not bool(np.any(noncoincident)):
                return estimate
            weights = 1.0 / distances[noncoincident]
            weighted = np.sum(
                points[noncoincident] * weights[:, None], axis=0
            ) / float(np.sum(weights))
            coincident_count = int(np.count_nonzero(~noncoincident))
            if coincident_count:
                residual = np.sum(
                    (points[noncoincident] - estimate)
                    / distances[noncoincident, None],
                    axis=0,
                )
                residual_norm = float(np.linalg.norm(residual))
                if residual_norm <= coincident_count:
                    return estimate
                retained = coincident_count / residual_norm
                updated = retained * estimate + (1.0 - retained) * weighted
            else:
                updated = weighted
            if float(np.linalg.norm(updated - estimate)) <= 1e-12:
                return updated
            estimate = updated
        return estimate

    @staticmethod
    def _independent_z_leverage_metrics(
        deltas: np.ndarray,
    ) -> dict[str, Any]:
        values = np.asarray(deltas, dtype=float)
        nuisance = np.column_stack(
            (np.ones(len(values)), values[:, 0], values[:, 1])
        )
        if np.linalg.matrix_rank(nuisance) < 3:
            raise CalibrationError(
                "USB carriage motion has insufficient independent Z leverage "
                "because commanded X/Y are not independently observable"
            )
        commanded_z = values[:, 2]
        projected_z = nuisance @ np.linalg.lstsq(
            nuisance, commanded_z, rcond=None
        )[0]
        residualized_z = commanded_z - projected_z
        centered_z = commanded_z - float(np.mean(commanded_z))
        centered_energy = float(np.dot(centered_z, centered_z))
        residualized_energy = float(np.dot(residualized_z, residualized_z))
        if centered_energy <= 1e-9 or residualized_energy <= 1e-9:
            raise CalibrationError(
                "USB carriage motion has insufficient independent Z leverage "
                "after residualizing commanded X/Y"
            )
        leverage_fractions = np.square(residualized_z) / residualized_energy
        return {
            "residualized_z": residualized_z,
            "residualized_energy": residualized_energy,
            "ratio": math.sqrt(residualized_energy / centered_energy),
            "rms_mm": math.sqrt(residualized_energy / len(residualized_z)),
            "span_mm": float(np.ptp(residualized_z)),
            "maximum_fraction": float(np.max(leverage_fractions)),
            "effective_samples": float(
                1.0 / np.sum(np.square(leverage_fractions))
            ),
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
                    "pnp_board_frame_normalization",
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
                pi_camera = self._cameras["pi"]
                pi_photometric_context = getattr(
                    pi_camera, "matched_photometric_controls", None
                )
                if not callable(pi_photometric_context):
                    raise CalibrationError(
                        "Pi Camera cannot guarantee matched ambient/laser photometry"
                    )
                settle_s = float(
                    self._config.get("laser_photometric_settle_s", 1.0)
                )
                if not math.isfinite(settle_s) or settle_s < 0:
                    raise CalibrationError(
                        "laser photometric settle time must be finite and non-negative"
                    )
                with pi_photometric_context() as pi_session:
                    self._sleep_interruptible(settle_s)
                    settled_metadata = self._hardware_call(
                        "Pi Camera settled ambient metadata",
                        pi_session.capture_metadata,
                        float(self._config.get("capture_timeout_s", 5.0)),
                    )
                    pi_photometry = self._hardware_call(
                        "Pi Camera ambient photometric lock",
                        lambda: pi_session.lock_from_metadata(
                            settled_metadata
                        ),
                        float(self._config.get("capture_timeout_s", 5.0)),
                    )
                    self._hardware_call(
                        "Pi Camera ambient photometric confirmation",
                        pi_session.confirm_locked_controls,
                        float(self._config.get("capture_timeout_s", 5.0)),
                    )
                    ambient_pi, ambient_metadata = self._capture_matched_pi(
                        pi_session
                    )
                    ambient = {"pi": ambient_pi}
                    ambient_photometry = pi_session.metadata_for_report(
                        ambient_metadata
                    )
                    usb_unavailable = (
                        "camera 'usb' has no verified matched-photometry "
                        "capture path"
                    )
                    for side in ("left", "right"):
                        self._laser(side, True)
                        try:
                            self._sleep_interruptible(
                                float(self._config.get("laser_settle_s", 0.1))
                            )
                            for name in ("pi", "usb"):
                                checkerboard_view = (
                                    self._checkerboard_view_for_pose(
                                        checkerboard_views, name, pose
                                    )
                                )
                                unavailable_reason = None
                                if (
                                    checkerboard_views is not None
                                    and checkerboard_view is None
                                ):
                                    unavailable_reason = (
                                        "no accepted exact-pose checkerboard view"
                                    )
                                if name == "usb":
                                    unavailable_reason = (
                                        "optional USB matched photometry/capture "
                                        f"unavailable: {usb_unavailable}"
                                    )
                                if unavailable_reason is not None:
                                    laser_photometry = None
                                    extracted = {
                                        "points": [],
                                        "diagnostic": {
                                            "accepted": False,
                                            "reason": unavailable_reason,
                                        },
                                    }
                                else:
                                    laser, laser_metadata = (
                                        self._capture_matched_pi(pi_session)
                                    )
                                    laser_photometry = (
                                        pi_session.metadata_for_report(
                                            laser_metadata
                                        )
                                    )
                                    extracted = self._laser_board_points(
                                        name,
                                        side,
                                        ambient[name],
                                        laser,
                                        pose,
                                        calibration,
                                        checkerboard_view=checkerboard_view,
                                    )
                                diagnostic = copy.deepcopy(
                                    extracted["diagnostic"]
                                )
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
                                    photometric_controls=copy.deepcopy(
                                        pi_photometry if name == "pi" else None
                                    ),
                                    photometry_matched=(name == "pi"),
                                    ambient_photometric_metadata=(
                                        copy.deepcopy(ambient_photometry)
                                        if name == "pi"
                                        else None
                                    ),
                                    laser_photometric_metadata=copy.deepcopy(
                                        laser_photometry
                                    ),
                                    checkerboard_source=(
                                        "cached"
                                        if checkerboard_view is not None
                                        else "missing-cache"
                                        if checkerboard_views is not None
                                        else diagnostic.get(
                                            "checkerboard_source",
                                            "ambient-detection",
                                        )
                                    ),
                                )
                                with self._lock:
                                    self._status["laser_views"][side][
                                        name
                                    ].append(diagnostic)
                                if diagnostic["accepted"]:
                                    samples[side][name].extend(
                                        extracted["points"]
                                    )
                                    sample_pose_indexes[side][name].extend(
                                        [pose_index] * len(extracted["points"])
                                    )
                                    accepted_pose_indexes[side][name].add(
                                        pose_index
                                    )
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
        minimum_points_per_view = int(
            self._config.get("minimum_laser_points_per_view", 10)
        )
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
            try:
                normal, offset, quality = self._fit_laser_plane_views(
                    samples[side]["pi"],
                    sample_pose_indexes[side]["pi"],
                    poses,
                    minimum_points=minimum_points,
                    minimum_points_per_view=minimum_points_per_view,
                    minimum_views=minimum_views,
                    minimum_orientations=minimum_orientations,
                    maximum_rms=maximum_rms,
                )
            except LaserPlaneConsensusError as exc:
                quality = copy.deepcopy(exc.quality)
                quality.update(
                    accepted=False,
                    primary_camera="pi",
                    camera_views=len(accepted_pose_indexes[side]["pi"]),
                    rejected_camera_views=len(poses)
                    - len(accepted_pose_indexes[side]["pi"]),
                    maximum_rms_mm=maximum_rms,
                )
                self._record_laser_pose_consensus(side, quality)
                with self._lock:
                    self._status["metrics"][f"laser_{side}"] = copy.deepcopy(
                        quality
                    )
                raise CalibrationError(f"{side} laser plane consensus failed: {exc}") from exc
            quality.update(
                primary_camera="pi",
                camera_views=len(accepted_pose_indexes[side]["pi"]),
                rejected_camera_views=len(poses)
                - len(accepted_pose_indexes[side]["pi"]),
            )
            quality["maximum_rms_mm"] = maximum_rms
            self._record_laser_pose_consensus(side, quality)
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

    def _record_laser_pose_consensus(
        self, side: str, quality: Mapping[str, Any]
    ) -> None:
        per_pose = {
            entry.get("pose_index"): entry
            for entry in quality.get("per_pose_residuals", [])
            if isinstance(entry, Mapping)
        }
        with self._lock:
            for diagnostic in self._status["laser_views"][side]["pi"]:
                pose_quality = per_pose.get(diagnostic.get("pose_index"))
                if not diagnostic.get("accepted") or pose_quality is None:
                    continue
                diagnostic["plane_consensus_retained"] = bool(
                    pose_quality.get("retained")
                )
                diagnostic["plane_consensus_reason"] = pose_quality.get("reason")
                diagnostic["plane_consensus_rms_mm"] = pose_quality.get("rms_mm")
                diagnostic["plane_consensus_inlier_points"] = pose_quality.get(
                    "inlier_points"
                )
                diagnostic["plane_consensus_inlier_fraction"] = pose_quality.get(
                    "inlier_fraction"
                )

    @staticmethod
    def _canonical_plane(
        normal: np.ndarray, offset: float
    ) -> tuple[np.ndarray, float]:
        normal = np.asarray(normal, dtype=float)
        pivot = int(np.argmax(np.abs(normal)))
        if normal[pivot] < 0:
            return -normal, -float(offset)
        return normal, float(offset)

    @staticmethod
    def _fit_plane_tls(points: np.ndarray) -> tuple[np.ndarray, float]:
        values = np.asarray(points, dtype=float)
        if values.ndim != 2 or values.shape[1] != 3 or len(values) < 3:
            raise CalibrationError("laser plane hypothesis has insufficient points")
        center = values.mean(axis=0)
        _, singular_values, vh = np.linalg.svd(
            values - center, full_matrices=False
        )
        if (
            len(singular_values) < 2
            or singular_values[0] <= 1e-12
            or singular_values[1] / singular_values[0] <= 1e-6
        ):
            raise CalibrationError("laser plane hypothesis has insufficient 2D spread")
        normal = vh[-1]
        normal /= np.linalg.norm(normal)
        return GeometricCalibrationService._canonical_plane(
            normal, -float(np.dot(normal, center))
        )

    @staticmethod
    def _bounded_group_indexes(indexes: np.ndarray, limit: int) -> np.ndarray:
        indexes = np.asarray(indexes, dtype=int)
        if len(indexes) <= limit:
            return indexes
        positions = np.linspace(0, len(indexes) - 1, limit)
        return indexes[np.rint(positions).astype(int)]

    def _fit_laser_plane_views(
        self,
        points: list[list[float]],
        pose_indexes: list[int],
        poses: list[Mapping[str, float]],
        *,
        minimum_points: int,
        minimum_points_per_view: int,
        minimum_views: int,
        minimum_orientations: int,
        maximum_rms: float = 2.0,
    ) -> tuple[np.ndarray, float, dict[str, Any]]:
        values = np.asarray(points, dtype=float)
        labels = np.asarray(pose_indexes, dtype=int)
        if len(values) != len(labels):
            raise CalibrationError("laser point and pose labels differ")
        if (
            values.ndim != 2
            or values.shape[1] != 3
            or not np.isfinite(values).all()
            or len(values) < minimum_points
        ):
            raise CalibrationError("laser plane points are insufficient or invalid")
        if minimum_points_per_view <= 0:
            raise CalibrationError(
                "minimum laser points per view must be positive"
            )
        if (
            minimum_views < 3
            or minimum_orientations < 3
            or not math.isfinite(maximum_rms)
            or not 0 < maximum_rms <= 2.0
        ):
            raise CalibrationError("laser plane consensus safety limits are invalid")
        unique_pose_indexes = sorted(int(index) for index in np.unique(labels))
        if (
            not unique_pose_indexes
            or unique_pose_indexes[0] < 0
            or unique_pose_indexes[-1] >= len(poses)
        ):
            raise CalibrationError("laser point pose label is outside the trajectory")

        residual_threshold = float(
            self._config.get(
                "laser_pose_residual_threshold_mm", min(maximum_rms, 2.0)
            )
        )
        minimum_inlier_fraction = float(
            self._config.get("minimum_laser_pose_inlier_fraction", 0.75)
        )
        minimum_retained_fraction = float(
            self._config.get("minimum_laser_pose_consensus_fraction", 0.75)
        )
        maximum_rejected_fraction = float(
            self._config.get("maximum_laser_rejected_pose_fraction", 0.25)
        )
        maximum_hypotheses = int(
            self._config.get("maximum_laser_pose_hypotheses", 128)
        )
        maximum_points_per_pose = int(
            self._config.get("maximum_laser_hypothesis_points_per_pose", 64)
        )
        minimum_spread_ratio = float(
            self._config.get("minimum_laser_plane_spread_ratio", 1e-3)
        )
        ambiguity_angle = float(
            self._config.get("laser_plane_ambiguity_normal_deg", 3.0)
        )
        ambiguity_offset = float(
            self._config.get("laser_plane_ambiguity_offset_mm", 2.0)
        )
        similar_support_fraction = float(
            self._config.get(
                "laser_plane_ambiguity_support_difference_fraction", 0.10
            )
        )
        if (
            not 0 < residual_threshold <= min(maximum_rms, 2.0)
            or minimum_points < 30
            or minimum_points_per_view < 10
            or not 0.75 <= minimum_inlier_fraction <= 1.0
            or not 0.75 <= minimum_retained_fraction <= 1.0
            or not 0 <= maximum_rejected_fraction <= 0.25
            or not 1 <= maximum_hypotheses <= 128
            or not minimum_points_per_view
            <= maximum_points_per_pose
            <= 256
            or not 1e-3 <= minimum_spread_ratio < 1.0
            or not 0 < ambiguity_angle <= 15.0
            or not 0 < ambiguity_offset <= 2.0
            or not 0 <= similar_support_fraction <= 0.25
        ):
            raise CalibrationError("laser pose consensus configuration is unsafe")

        groups = {
            index: np.flatnonzero(labels == index) for index in unique_pose_indexes
        }
        original_pose_count = len(unique_pose_indexes)
        required_retained_poses = max(
            minimum_views,
            int(math.ceil(original_pose_count * minimum_retained_fraction)),
            int(math.ceil(original_pose_count * (1.0 - maximum_rejected_fraction))),
        )

        def balanced_indexes(
            selected_groups: list[int],
            masks: Mapping[int, np.ndarray] | None = None,
        ) -> np.ndarray:
            available = []
            for index in selected_groups:
                indexes = groups[index]
                if masks is not None:
                    indexes = indexes[np.asarray(masks[index], dtype=bool)]
                if len(indexes):
                    available.append(indexes)
            if not available:
                return np.asarray([], dtype=int)
            count = min(maximum_points_per_pose, *(len(indexes) for indexes in available))
            return np.concatenate(
                [
                    self._bounded_group_indexes(indexes, count)
                    for indexes in available
                ]
            )

        def score_plane(normal: np.ndarray, offset: float) -> dict[str, Any]:
            distances = np.abs(values @ normal + offset)
            per_pose = []
            retained = []
            masks = {}
            pose_rms = []
            for index in unique_pose_indexes:
                pose_distances = distances[groups[index]]
                mask = pose_distances <= residual_threshold
                masks[index] = mask
                inlier_count = int(np.count_nonzero(mask))
                fraction = inlier_count / len(pose_distances)
                keep = (
                    inlier_count >= minimum_points_per_view
                    and fraction >= minimum_inlier_fraction
                )
                if keep:
                    retained.append(index)
                    pose_rms.append(
                        float(np.sqrt(np.mean(pose_distances[mask] ** 2)))
                    )
                    reason = None
                elif inlier_count < minimum_points_per_view:
                    reason = (
                        f"{inlier_count} points within {residual_threshold:.2f}mm; "
                        f"{minimum_points_per_view} required"
                    )
                else:
                    reason = (
                        f"inlier fraction {fraction:.3f} below "
                        f"{minimum_inlier_fraction:.3f}"
                    )
                per_pose.append(
                    {
                        "pose_index": index,
                        "original_points": int(len(pose_distances)),
                        "inlier_points": inlier_count,
                        "inlier_fraction": float(fraction),
                        "retained": keep,
                        "reason": reason,
                        "rms_mm": float(np.sqrt(np.mean(pose_distances**2))),
                        "inlier_rms_mm": (
                            float(np.sqrt(np.mean(pose_distances[mask] ** 2)))
                            if inlier_count
                            else None
                        ),
                        "median_mm": float(np.median(pose_distances)),
                        "p90_mm": float(np.percentile(pose_distances, 90)),
                        "p95_mm": float(np.percentile(pose_distances, 95)),
                        "maximum_mm": float(np.max(pose_distances)),
                    }
                )
            orientations = self._independent_board_orientation_count(
                [poses[index] for index in retained]
            )
            return {
                "normal": normal,
                "offset": offset,
                "retained": tuple(retained),
                "masks": masks,
                "per_pose": per_pose,
                "orientations": orientations,
                "balanced_rms": (
                    float(np.sqrt(np.mean(np.square(pose_rms))))
                    if pose_rms
                    else math.inf
                ),
            }

        eligible_groups = [
            index
            for index in unique_pose_indexes
            if len(groups[index]) >= minimum_points_per_view
        ]
        hypothesis_groups: list[tuple[int, ...]] = []
        if len(eligible_groups) >= 3:
            hypothesis_groups.append(tuple(eligible_groups))
        hypothesis_groups.extend(
            (eligible_groups[left], eligible_groups[right])
            for left in range(len(eligible_groups))
            for right in range(left + 1, len(eligible_groups))
        )
        base_quality = {
            "accepted": False,
            "consensus_method": "deterministic_pose_balanced_v1",
            "original_accepted_poses": original_pose_count,
            "required_retained_poses": required_retained_poses,
            "minimum_retained_pose_fraction": minimum_retained_fraction,
            "maximum_rejected_pose_fraction": maximum_rejected_fraction,
            "pose_residual_threshold_mm": residual_threshold,
            "minimum_pose_inlier_fraction": minimum_inlier_fraction,
            "hypotheses_evaluated": 0,
            "candidate_hypotheses": len(hypothesis_groups),
            "maximum_pose_hypotheses": maximum_hypotheses,
            "maximum_hypothesis_points_per_pose": maximum_points_per_pose,
            "ambiguity_checked": False,
            "ambiguous": False,
            "minimum_views": minimum_views,
            "minimum_board_orientations": minimum_orientations,
            "minimum_points": minimum_points,
            "minimum_points_per_view": minimum_points_per_view,
            "minimum_plane_spread_ratio": minimum_spread_ratio,
        }
        if len(hypothesis_groups) > maximum_hypotheses:
            raise LaserPlaneConsensusError(
                f"{len(hypothesis_groups)} pose hypotheses exceed the fail-closed "
                f"bound of {maximum_hypotheses}",
                base_quality,
            )

        candidates: list[dict[str, Any]] = []
        raw_candidates: list[dict[str, Any]] = []
        for hypothesis_index, source_groups in enumerate(hypothesis_groups):
            indexes = balanced_indexes(list(source_groups))
            try:
                normal, offset = self._fit_plane_tls(values[indexes])
            except CalibrationError:
                continue
            scored = score_plane(normal, offset)
            raw_scored = dict(scored)
            raw_scored["hypothesis_index"] = hypothesis_index
            raw_scored["source_groups"] = source_groups
            raw_scored["rank"] = (
                len(raw_scored["retained"]),
                raw_scored["orientations"],
                -raw_scored["balanced_rms"],
                -hypothesis_index,
            )
            raw_candidates.append(raw_scored)
            for _ in range(original_pose_count + 2):
                if len(scored["retained"]) < 2:
                    break
                indexes = balanced_indexes(
                    list(scored["retained"]), scored["masks"]
                )
                try:
                    refined_normal, refined_offset = self._fit_plane_tls(
                        values[indexes]
                    )
                except CalibrationError:
                    break
                refined = score_plane(refined_normal, refined_offset)
                if (
                    refined["retained"] == scored["retained"]
                    and math.degrees(
                        math.acos(
                            np.clip(
                                abs(float(np.dot(refined_normal, normal))),
                                0.0,
                                1.0,
                            )
                        )
                    )
                    < 1e-8
                    and abs(refined_offset - offset) < 1e-8
                ):
                    scored = refined
                    break
                normal, offset, scored = refined_normal, refined_offset, refined
            scored["hypothesis_index"] = hypothesis_index
            scored["source_groups"] = source_groups
            scored["rank"] = (
                len(scored["retained"]),
                scored["orientations"],
                -scored["balanced_rms"],
                -hypothesis_index,
            )
            equivalent = any(
                prior["retained"] == scored["retained"]
                and math.degrees(
                    math.acos(
                        np.clip(
                            abs(float(np.dot(prior["normal"], scored["normal"]))),
                            0.0,
                            1.0,
                        )
                    )
                )
                < 1e-6
                and abs(prior["offset"] - scored["offset"]) < 1e-6
                for prior in candidates
            )
            if not equivalent:
                candidates.append(scored)

        base_quality.update(
            hypotheses_evaluated=len(hypothesis_groups),
            ambiguity_checked=True,
        )
        if not candidates:
            raise LaserPlaneConsensusError(
                "no bounded pose-pair plane hypothesis had adequate 2D spread",
                base_quality,
            )

        ordered = sorted(candidates, key=lambda item: item["rank"], reverse=True)
        ambiguity_candidates: list[dict[str, Any]] = []
        for candidate in raw_candidates + ordered:
            if any(
                prior["retained"] == candidate["retained"]
                and math.degrees(
                    math.acos(
                        np.clip(
                            abs(
                                float(
                                    np.dot(
                                        prior["normal"], candidate["normal"]
                                    )
                                )
                            ),
                            0.0,
                            1.0,
                        )
                    )
                )
                < 1e-6
                and abs(prior["offset"] - candidate["offset"]) < 1e-6
                for prior in ambiguity_candidates
            ):
                continue
            ambiguity_candidates.append(candidate)
        ambiguity_candidates.sort(key=lambda item: item["rank"], reverse=True)
        support_difference = int(
            math.floor(original_pose_count * similar_support_fraction)
        )
        ambiguity_minimum_support = (
            required_retained_poses
            if any(
                len(candidate["retained"]) >= required_retained_poses
                for candidate in ambiguity_candidates
            )
            else max(
                len(candidate["retained"]) for candidate in ambiguity_candidates
            )
        )
        ambiguity = None
        for left_position, left in enumerate(ambiguity_candidates):
            if len(left["retained"]) < max(2, ambiguity_minimum_support):
                continue
            for right in ambiguity_candidates[left_position + 1 :]:
                if (
                    len(right["retained"]) < max(2, ambiguity_minimum_support)
                    or abs(len(left["retained"]) - len(right["retained"]))
                    > support_difference
                ):
                    continue
                normal_angle = math.degrees(
                    math.acos(
                        np.clip(
                            abs(float(np.dot(left["normal"], right["normal"]))),
                            0.0,
                            1.0,
                        )
                    )
                )
                offset_delta = abs(left["offset"] - right["offset"])
                if (
                    normal_angle >= ambiguity_angle
                    or offset_delta >= ambiguity_offset
                ):
                    ambiguity = {
                        "first_pose_indexes": list(left["retained"]),
                        "second_pose_indexes": list(right["retained"]),
                        "normal_angle_deg": normal_angle,
                        "offset_delta_mm": offset_delta,
                    }
                    break
            if ambiguity is not None:
                break
        if ambiguity is not None:
            base_quality.update(
                ambiguous=True,
                ambiguity=ambiguity,
                per_pose_residuals=ordered[0]["per_pose"],
            )
            raise LaserPlaneConsensusError(
                "ambiguous competing laser planes have similar pose support",
                base_quality,
            )

        viable = [
            candidate
            for candidate in ordered
            if len(candidate["retained"]) >= required_retained_poses
            and candidate["orientations"] >= minimum_orientations
        ]
        selected = viable[0] if viable else ordered[0]
        if (
            len(selected["retained"]) < required_retained_poses
            or selected["orientations"] < minimum_orientations
        ):
            base_quality.update(
                views=len(selected["retained"]),
                independent_board_orientations=selected["orientations"],
                retained_pose_fraction=(
                    len(selected["retained"]) / original_pose_count
                ),
                per_pose_residuals=selected["per_pose"],
                rejected_poses=[
                    {
                        "pose_index": entry["pose_index"],
                        "reason": entry["reason"],
                    }
                    for entry in selected["per_pose"]
                    if not entry["retained"]
                ],
            )
            raise LaserPlaneConsensusError(
                "laser robust fit retains only "
                f"{len(selected['retained'])} Pi poses and "
                f"{selected['orientations']} independent orientations; requires "
                f"{required_retained_poses} poses and {minimum_orientations} orientations",
                base_quality,
            )

        final_score = selected
        fit_quality = None
        for _ in range(original_pose_count + 2):
            indexes = balanced_indexes(
                list(final_score["retained"]), final_score["masks"]
            )
            try:
                normal, offset, fit_quality = fit_plane_robust(
                    values[indexes],
                    minimum_points=minimum_points,
                    minimum_spread_ratio=minimum_spread_ratio,
                )
            except CalibrationError as exc:
                base_quality.update(
                    views=len(final_score["retained"]),
                    independent_board_orientations=final_score["orientations"],
                    per_pose_residuals=final_score["per_pose"],
                )
                raise LaserPlaneConsensusError(
                    f"balanced robust laser-plane refit failed: {exc}",
                    base_quality,
                ) from exc
            normal, offset = self._canonical_plane(normal, offset)
            rescored = score_plane(normal, offset)
            if rescored["retained"] == final_score["retained"]:
                final_score = rescored
                break
            final_score = rescored
            if (
                len(final_score["retained"]) < required_retained_poses
                or final_score["orientations"] < minimum_orientations
            ):
                base_quality.update(
                    views=len(final_score["retained"]),
                    independent_board_orientations=final_score["orientations"],
                    retained_pose_fraction=(
                        len(final_score["retained"]) / original_pose_count
                    ),
                    per_pose_residuals=final_score["per_pose"],
                )
                raise LaserPlaneConsensusError(
                    "pose support fell below the safety gates during balanced robust refit",
                    base_quality,
                )
        else:
            raise LaserPlaneConsensusError(
                "laser pose consensus did not converge within its deterministic bound",
                base_quality,
            )

        retained_indexes = list(final_score["retained"])
        final_inlier_indexes = np.concatenate(
            [
                groups[index][final_score["masks"][index]]
                for index in retained_indexes
            ]
        )
        final_residuals = values[final_inlier_indexes] @ normal + offset
        final_rms = float(np.sqrt(np.mean(final_residuals**2)))
        if final_rms > maximum_rms:
            base_quality.update(
                rms_mm=final_rms,
                views=len(retained_indexes),
                independent_board_orientations=final_score["orientations"],
                per_pose_residuals=final_score["per_pose"],
            )
            raise LaserPlaneConsensusError(
                f"no pose consensus subset passes the {maximum_rms:.2f}mm RMS gate",
                base_quality,
            )

        leave_one_out = []
        for omitted in retained_indexes:
            training_groups = [
                index for index in retained_indexes if index != omitted
            ]
            training_indexes = balanced_indexes(
                training_groups, final_score["masks"]
            )
            diagnostic = {"pose_index": omitted, "fit_available": False}
            try:
                loo_normal, loo_offset = self._fit_plane_tls(
                    values[training_indexes]
                )
                held_residuals = values[groups[omitted]] @ loo_normal + loo_offset
                training_residuals = (
                    values[training_indexes] @ loo_normal + loo_offset
                )
                diagnostic.update(
                    fit_available=True,
                    training_rms_mm=float(
                        np.sqrt(np.mean(training_residuals**2))
                    ),
                    held_out_rms_mm=float(
                        np.sqrt(np.mean(held_residuals**2))
                    ),
                    normal_delta_deg=math.degrees(
                        math.acos(
                            np.clip(
                                abs(float(np.dot(normal, loo_normal))),
                                0.0,
                                1.0,
                            )
                        )
                    ),
                    offset_delta_mm=abs(offset - loo_offset),
                )
            except CalibrationError as exc:
                diagnostic["reason"] = str(exc)
            leave_one_out.append(diagnostic)

        assert fit_quality is not None
        fit_quality.update(
            accepted=True,
            rms_mm=final_rms,
            inliers=int(len(final_inlier_indexes)),
            samples=int(len(values)),
            views=len(retained_indexes),
            independent_board_orientations=final_score["orientations"],
            minimum_views=minimum_views,
            minimum_board_orientations=minimum_orientations,
            minimum_points=minimum_points,
            minimum_points_per_view=minimum_points_per_view,
            inlier_points_per_pose=[
                {
                    "pose_index": index,
                    "points": int(
                        np.count_nonzero(final_score["masks"][index])
                    ),
                }
                for index in retained_indexes
            ],
            consensus_method="deterministic_pose_balanced_v1",
            original_accepted_poses=original_pose_count,
            required_retained_poses=required_retained_poses,
            retained_pose_fraction=len(retained_indexes) / original_pose_count,
            minimum_retained_pose_fraction=minimum_retained_fraction,
            rejected_pose_fraction=(
                (original_pose_count - len(retained_indexes))
                / original_pose_count
            ),
            maximum_rejected_pose_fraction=maximum_rejected_fraction,
            pose_residual_threshold_mm=residual_threshold,
            minimum_pose_inlier_fraction=minimum_inlier_fraction,
            hypotheses_evaluated=len(hypothesis_groups),
            maximum_pose_hypotheses=maximum_hypotheses,
            maximum_hypothesis_points_per_pose=maximum_points_per_pose,
            ambiguity_checked=True,
            ambiguous=False,
            per_pose_residuals=final_score["per_pose"],
            rejected_poses=[
                {
                    "pose_index": entry["pose_index"],
                    "reason": entry["reason"],
                }
                for entry in final_score["per_pose"]
                if not entry["retained"]
            ],
            leave_one_pose_out=leave_one_out,
        )
        return normal, offset, fit_quality

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

    def _capture_matched_pi(self, session: Any) -> tuple[bytes, dict]:
        frame = self._hardware_call(
            "Pi Camera matched photometric capture",
            session.capture_jpeg,
            float(self._config.get("capture_timeout_s", 5.0)),
        )
        if (
            not isinstance(frame, tuple)
            or len(frame) != 2
            or not frame[0]
            or not isinstance(frame[1], dict)
        ):
            raise CalibrationError(
                "Pi Camera returned no verified matched photometric frame"
            )
        return frame

    def _laser(self, side: str, enabled: bool) -> None:
        with self._lock:
            if enabled:
                self._check_cancelled()
            if enabled:
                method = getattr(
                    self._gpio,
                    "laser_on_for_calibration",
                    self._gpio.laser_on,
                )
            else:
                method = self._gpio.laser_off
            if not method(side):
                raise CalibrationError(
                    f"failed to turn laser {side} {'on' if enabled else 'off'}"
                )

    def _lasers_off(self) -> None:
        failures = []
        with self._lock:
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
