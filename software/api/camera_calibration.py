"""
Camera Calibration Pose Manager

Defines the calibration poses for Pi Camera and Logitech USB camera,
provides motor-move logic, and persists the scan-reference pose.

Motion convention:
  X = centre / advance-retreat of the turntable
  Y = rotation of the turntable
  Z = height  (Pi Camera: DO NOT touch Z)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default calibration poses
# ---------------------------------------------------------------------------

# Pi Camera: X/Y only — Z must not be modified.
PI_CAMERA_CALIBRATION_POSE: dict[str, float | None] = {
    "x": 0.0,
    "y": 0.0,
    "z": None,   # None = do not move Z
}

# Logitech USB camera: X/Y/Z — all three axes are used.
LOGITECH_CALIBRATION_POSE: dict[str, float | None] = {
    "x": 0.0,
    "y": 0.0,
    "z": 50.0,
}

_POSES: dict[str, dict[str, float | None]] = {
    "pi": PI_CAMERA_CALIBRATION_POSE,
    "usb": LOGITECH_CALIBRATION_POSE,
}

# Tolerance (mm) for TF-Luna distance validation
DISTANCE_TOLERANCE_MM = 10.0

# ---------------------------------------------------------------------------
# Scan-pose persistence
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_POSE_PATH = _REPO_ROOT / "config" / "scan_poses.json"
SCAN_POSE_PATH = os.environ.get("HORALSCANNER_SCAN_POSES", str(_DEFAULT_POSE_PATH))


def load_scan_poses() -> dict[str, Any]:
    """Load persisted scan poses from disk."""
    try:
        with open(SCAN_POSE_PATH, "r") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in scan poses file: %s", exc)
        return {}


def save_scan_poses(poses: dict[str, Any]) -> None:
    """Persist scan poses to disk."""
    os.makedirs(os.path.dirname(SCAN_POSE_PATH), exist_ok=True)
    with open(SCAN_POSE_PATH, "w") as fh:
        json.dump(poses, fh, indent=2)
    logger.info("Scan poses saved to %s", SCAN_POSE_PATH)


# ---------------------------------------------------------------------------
# Calibration pose helper
# ---------------------------------------------------------------------------

def get_calibration_pose(camera: str) -> dict[str, float | None] | None:
    """Return the calibration pose for *camera* ('pi' or 'usb'), or None."""
    return _POSES.get(camera)


def move_to_calibration_pose(
    camera: str,
    stm32_driver: Any,
    lidar_driver: Any | None = None,
) -> dict[str, Any]:
    """Move motors to the calibration pose for *camera*.

    Parameters
    ----------
    camera:
        ``'pi'`` or ``'usb'``.
    stm32_driver:
        The STM32 driver instance (must expose ``move_motor(axis, mm)``).
    lidar_driver:
        Optional TF-Luna driver.  Distance is read (if connected) and included
        in the return value for validation/display purposes.

    Returns
    -------
    dict with keys:
        ``ok`` (bool), ``camera``, ``pose``, ``axes_moved``,
        ``lidar_distance_mm`` (float | None), ``lidar_within_tolerance`` (bool | None).
    """
    pose = get_calibration_pose(camera)
    if pose is None:
        return {"ok": False, "error": f"Caméra inconnue : {camera!r}"}

    if stm32_driver is None:
        return {"ok": False, "error": "Pilote STM32 non disponible"}

    axes_moved: list[str] = []
    try:
        for axis in ("x", "y", "z"):
            target = pose.get(axis)
            if target is None:
                continue  # skip Z for Pi Camera
            stm32_driver.move_motor(axis, target)
            axes_moved.append(axis.upper())
    except Exception:
        logger.exception("Motor move failed during calibration pose for %s", camera)
        return {"ok": False, "error": "Mouvement moteur échoué"}

    # Read TF-Luna distance if available
    lidar_distance_mm: float | None = None
    lidar_within_tolerance: bool | None = None
    if lidar_driver is not None:
        try:
            dist = lidar_driver.read_distance_mm()
            if dist is not None:
                lidar_distance_mm = dist
                # For Logitech we can also compare against the Z target
                reference = pose.get("z")
                if reference is not None:
                    lidar_within_tolerance = abs(dist - reference) <= DISTANCE_TOLERANCE_MM
        except Exception as exc:
            logger.warning("TF-Luna read failed during calibration: %s", exc)

    return {
        "ok": True,
        "camera": camera,
        "pose": {k: v for k, v in pose.items() if v is not None},
        "axes_moved": axes_moved,
        "lidar_distance_mm": lidar_distance_mm,
        "lidar_within_tolerance": lidar_within_tolerance,
    }


# ---------------------------------------------------------------------------
# Scan-pose memory (in-process + optional persistence)
# ---------------------------------------------------------------------------

# In-memory store; keyed by camera name.
_scan_poses: dict[str, dict[str, float]] = {}


def _load_initial_poses() -> None:
    global _scan_poses
    _scan_poses = load_scan_poses()


_load_initial_poses()


def get_all_saved_poses() -> dict[str, dict[str, float]]:
    """Return a copy of all in-memory saved scan poses."""
    return dict(_scan_poses)


def save_current_pose(camera: str, stm32_driver: Any) -> dict[str, Any]:
    """Read the current motor positions and save them as the scan pose for *camera*."""
    if stm32_driver is None:
        return {"ok": False, "error": "Pilote STM32 non disponible"}

    try:
        status = stm32_driver.get_motor_status()
    except Exception:
        logger.exception("Failed to read motor status")
        return {"ok": False, "error": "Lecture de position échouée"}

    positions: dict[str, float] = status.get("positions", {})
    _scan_poses[camera] = {k: float(v) for k, v in positions.items()}

    try:
        save_scan_poses(_scan_poses)
    except Exception as exc:
        logger.warning("Could not persist scan poses: %s", exc)

    return {"ok": True, "camera": camera, "pose": _scan_poses[camera]}


def get_saved_pose(camera: str) -> dict[str, float] | None:
    """Return the saved scan pose for *camera*, or None if not set."""
    return _scan_poses.get(camera)


def restore_scan_pose(camera: str, stm32_driver: Any) -> dict[str, Any]:
    """Move motors to the saved scan pose for *camera*."""
    pose = get_saved_pose(camera)
    if pose is None:
        return {"ok": False, "error": f"Aucune pose mémorisée pour la caméra '{camera}'"}

    if stm32_driver is None:
        return {"ok": False, "error": "Pilote STM32 non disponible"}

    axes_moved: list[str] = []
    try:
        for axis, target in pose.items():
            stm32_driver.move_motor(axis, float(target))
            axes_moved.append(axis.upper())
    except Exception:
        logger.exception("Motor move failed during scan pose restore for %s", camera)
        return {"ok": False, "error": "Mouvement moteur échoué"}

    return {"ok": True, "camera": camera, "pose": pose, "axes_moved": axes_moved}
