"""Bounded, scale-aware checkerboard detection with a narrow IR-glare fallback."""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Iterable

import numpy as np


def _flags(cv: Any, names: Iterable[str]) -> int:
    return sum(int(getattr(cv, name, 0)) for name in names)


def _limited_ir_glare_mask(cv: Any, image: np.ndarray) -> np.ndarray | None:
    """Return a mask for one small saturated/chromatic blob, never broad whites."""
    if image.ndim != 3 or image.shape[2] < 3 or not hasattr(
        cv, "connectedComponentsWithStats"
    ):
        return None
    height, width = image.shape[:2]
    channels = image[:, :, :3].astype(np.int16)
    peak = channels.max(axis=2)
    chroma = peak - channels.min(axis=2)
    candidate = ((peak >= 235) & (chroma >= 28)).astype(np.uint8)
    if not candidate.any():
        return None

    try:
        count, labels, stats, _ = cv.connectedComponentsWithStats(
            candidate, connectivity=8
        )
    except TypeError:
        count, labels, stats, _ = cv.connectedComponentsWithStats(candidate, 8)
    area_index = int(getattr(cv, "CC_STAT_AREA", 4))
    left_index = int(getattr(cv, "CC_STAT_LEFT", 0))
    top_index = int(getattr(cv, "CC_STAT_TOP", 1))
    width_index = int(getattr(cv, "CC_STAT_WIDTH", 2))
    height_index = int(getattr(cv, "CC_STAT_HEIGHT", 3))
    maximum_area = max(16, int(width * height * 0.002))
    choices = []
    for label in range(1, int(count)):
        area = int(stats[label, area_index])
        blob_width = int(stats[label, width_index])
        blob_height = int(stats[label, height_index])
        left = int(stats[label, left_index])
        top = int(stats[label, top_index])
        aspect = blob_width / max(blob_height, 1)
        if (
            4 <= area <= maximum_area
            and blob_width <= max(8, int(width * 0.08))
            and blob_height <= max(8, int(height * 0.08))
            and 0.25 <= aspect <= 4.0
            and left > 0
            and top > 0
            and left + blob_width < width
            and top + blob_height < height
        ):
            choices.append((area, label))
    if not choices:
        return None

    _, selected = max(choices)
    mask = (labels == selected).astype(np.uint8) * 255
    if hasattr(cv, "dilate") and hasattr(cv, "getStructuringElement"):
        radius = max(1, int(round(min(width, height) * 0.004)))
        size = radius * 2 + 1
        shape = int(getattr(cv, "MORPH_ELLIPSE", 2))
        kernel = cv.getStructuringElement(shape, (size, size))
        mask = cv.dilate(mask, kernel, iterations=1)
    return mask


def _detect(
    cv: Any,
    image: np.ndarray,
    patterns: tuple[tuple[int, int], ...],
    max_width: int,
    allow_ir_glare_fallback: bool,
) -> dict:
    frame_height, frame_width = image.shape[:2]
    scale = 1.0
    analysis = image
    if max_width > 0 and frame_width > max_width:
        scale = max_width / frame_width
        analysis = cv.resize(
            image,
            (max_width, max(1, int(round(frame_height * scale)))),
            interpolation=cv.INTER_AREA,
        )

    classic_flags = _flags(
        cv, ("CALIB_CB_ADAPTIVE_THRESH", "CALIB_CB_NORMALIZE_IMAGE", "CALIB_CB_FAST_CHECK")
    )
    sb_flags = _flags(
        cv, ("CALIB_CB_NORMALIZE_IMAGE", "CALIB_CB_ACCURACY")
    )

    def attempts(candidate: np.ndarray, *, glare_masked: bool) -> dict | None:
        gray = cv.cvtColor(candidate, cv.COLOR_BGR2GRAY)
        for pattern in patterns:
            try:
                found, corners = cv.findChessboardCorners(gray, pattern, classic_flags)
            except TypeError:
                found, corners = cv.findChessboardCorners(gray, pattern)
            if found:
                if hasattr(cv, "cornerSubPix"):
                    criteria = (
                        int(getattr(cv, "TERM_CRITERIA_EPS", 2))
                        + int(getattr(cv, "TERM_CRITERIA_MAX_ITER", 1)),
                        30,
                        0.001,
                    )
                    corners = cv.cornerSubPix(gray, corners, (7, 7), (-1, -1), criteria)
                return {
                    "found": True,
                    "pattern": pattern,
                    "corners": np.asarray(corners, dtype=np.float32) / scale,
                    "method": "classic",
                    "glare_masked": glare_masked,
                }
            sb = getattr(cv, "findChessboardCornersSB", None)
            if sb is not None:
                try:
                    found, corners = sb(gray, pattern, sb_flags)
                except TypeError:
                    found, corners = sb(gray, pattern)
                if found:
                    return {
                        "found": True,
                        "pattern": pattern,
                        "corners": np.asarray(corners, dtype=np.float32) / scale,
                        "method": "sb",
                        "glare_masked": glare_masked,
                    }
        return None

    result = attempts(analysis, glare_masked=False)
    if result is not None or not allow_ir_glare_fallback or not hasattr(cv, "inpaint"):
        return result or {"found": False}
    mask = _limited_ir_glare_mask(cv, analysis)
    if mask is None:
        return {"found": False}
    inpaint_method = int(getattr(cv, "INPAINT_TELEA", 1))
    corrected = cv.inpaint(analysis, mask, 3, inpaint_method)
    result = attempts(corrected, glare_masked=True)
    if result is None:
        return {"found": False}
    analysis_points = np.asarray(result["corners"]).reshape(-1, 2) * scale
    for x, y in np.rint(analysis_points).astype(int):
        if 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x]:
            return {
                "found": False,
                "error": "IR glare mask overlaps a detected checkerboard corner",
            }
    result["glare_mask_area_px"] = int(np.count_nonzero(mask))
    return result


def find_checkerboard_bounded(
    cv: Any,
    image: np.ndarray,
    patterns: Iterable[tuple[int, int]],
    *,
    max_width: int = 1280,
    timeout_s: float = 2.0,
    allow_ir_glare_fallback: bool = True,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Detect a checkerboard and return corners in full captured-image coordinates."""
    if image is None or image.ndim != 3 or image.shape[2] < 3:
        return {"found": False, "error": "invalid image"}
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        return {"found": False, "error": "invalid timeout"}
    normalized_patterns = tuple((int(cols), int(rows)) for cols, rows in patterns)
    if not normalized_patterns:
        return {"found": False, "error": "no checkerboard pattern"}

    done = threading.Event()
    outcome: dict[str, Any] = {}

    def invoke() -> None:
        try:
            outcome["result"] = _detect(
                cv,
                image.copy(),
                normalized_patterns,
                int(max_width),
                allow_ir_glare_fallback,
            )
        except Exception as exc:
            outcome["error"] = str(exc)
        finally:
            done.set()

    threading.Thread(target=invoke, name="checkerboard-detection", daemon=True).start()
    deadline = time.monotonic() + timeout_s
    while not done.is_set():
        if cancel_event is not None and cancel_event.is_set():
            return {"found": False, "cancelled": True}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                "found": False,
                "timed_out": True,
                "error": "checkerboard detection timed out",
            }
        done.wait(min(0.05, remaining))
    if "error" in outcome:
        return {"found": False, "error": outcome["error"]}
    return outcome["result"]
