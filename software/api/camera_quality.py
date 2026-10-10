"""Lightweight, dependency-free camera frame quality check.

Pure OpenCV heuristics (brightness + blur) used to warn the operator when a
camera's physical setup is likely degraded (lens obstructed, out of focus,
poorly mounted) *without* blocking a scan. This is informational only: a
camera that is connected and able to produce frames should never be turned
into a hard scan blocker just because one frame looks dim or soft — the
camera may still be good enough to scan with, especially for a secondary/
auxiliary view (e.g. the "pi" laser camera while its mount is being fixed).

Mirrors the quality half of the Hailo-based ``hailo_vision.frame_quality``
module used on the IA Morgana companion board, but lives here so it has no
dependency on Hailo hardware and can run directly on HoralScanner.
"""

from __future__ import annotations

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without OpenCV
    cv2 = None
    _CV2_AVAILABLE = False

import numpy as np

# Thresholds (ajustables selon l'eclairage reel des postes).
DARK_MEAN_THRESHOLD = 18.0       # luminosite moyenne (0-255) en dessous = trop sombre
BLUR_VARIANCE_THRESHOLD = 25.0   # variance du Laplacien en dessous = flou


def frame_quality(image_bytes: bytes) -> dict:
    """Return brightness/blur quality metrics for a JPEG frame.

    Returns a dict with ``available`` (False if OpenCV is missing or the
    image could not be decoded) and, when available, ``mean_brightness``,
    ``blur_variance``, ``too_dark``, ``too_blurry`` and ``usable``.
    """
    if not _CV2_AVAILABLE:
        return {"available": False, "reason": "OpenCV not installed"}

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return {"available": False, "reason": "undecodable JPEG"}

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_brightness = float(gray.mean())
    blur_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    too_dark = mean_brightness < DARK_MEAN_THRESHOLD
    too_blurry = blur_variance < BLUR_VARIANCE_THRESHOLD

    return {
        "available": True,
        "mean_brightness": round(mean_brightness, 1),
        "blur_variance": round(blur_variance, 1),
        "too_dark": too_dark,
        "too_blurry": too_blurry,
        "usable": not (too_dark or too_blurry),
    }
