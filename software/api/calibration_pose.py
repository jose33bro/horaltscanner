"""
Calibration Pose - Camera calibration positioning and scan-pose memory.

Provides default calibration poses per camera type and a PoseMemory that
persists the saved scan pose to disk so the machine can return to it later.

Motion convention (from hardware spec):
  X = centre / advance-retreat of the turntable (plate centre positioning)
  Y = rotation of the turntable
  Z = height

Camera rules:
  Pi Camera   → move X and Y only; never touch Z.
  Logitech USB → move X, Y and Z; Z is used for height.
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

#: Pose applied when entering Pi Camera calibration.
#: Z is intentionally absent – it must never be modified for Pi Camera.
PI_CAMERA_DEFAULT_POSE: dict[str, float] = {
    "x": 100.0,
    "y": 0.0,
}

#: Pose applied when entering Logitech USB camera calibration.
#: Z adjusts the height for the USB camera viewpoint.
LOGITECH_DEFAULT_POSE: dict[str, float] = {
    "x": 100.0,
    "y": 0.0,
    "z": 150.0,
}

_CAMERA_DEFAULT_POSES: dict[str, dict[str, float]] = {
    "pi": PI_CAMERA_DEFAULT_POSE,
    "usb": LOGITECH_DEFAULT_POSE,
}


def get_default_pose(camera: str) -> dict[str, float] | None:
    """Return the default calibration pose for *camera* ('pi' or 'usb').

    Returns ``None`` if the camera name is unknown.
    """
    return _CAMERA_DEFAULT_POSES.get(camera)


# ---------------------------------------------------------------------------
# Pose memory
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_POSES_PATH = str(_REPO_ROOT / "config" / "scan_poses.json")


class PoseMemory:
    """Persist the saved scan pose for each camera to a JSON file.

    The file contains a top-level dict keyed by camera name::

        {
            "pi":  {"x": 100.0, "y": 5.0},
            "usb": {"x": 98.0,  "y": 2.0, "z": 152.0}
        }
    """

    def __init__(self, path: str | None = None) -> None:
        self._path = path or os.environ.get("HORALSCANNER_SCAN_POSES", _DEFAULT_POSES_PATH)
        self._data: dict[str, dict[str, float]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            with open(self._path) as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                self._data = raw
        except FileNotFoundError:
            self._data = {}
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("scan_poses.json invalid, resetting: %s", exc)
            self._data = {}

    def _save(self) -> None:
        parent = Path(self._path).parent
        if str(parent) not in ("", "."):
            os.makedirs(str(parent), exist_ok=True)
        with open(self._path, "w") as fh:
            json.dump(self._data, fh, indent=2)
        logger.info("Scan poses saved to %s", self._path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_pose(self, camera: str, pose: dict[str, float]) -> None:
        """Persist *pose* as the scan pose for *camera*."""
        self._data[camera] = {k: float(v) for k, v in pose.items()}
        self._save()

    def get_pose(self, camera: str) -> dict[str, float] | None:
        """Return the saved scan pose for *camera*, or ``None`` if not set."""
        return self._data.get(camera)

    def all_poses(self) -> dict[str, dict[str, float]]:
        """Return a copy of all saved poses."""
        return dict(self._data)


# ---------------------------------------------------------------------------
# Motor movement helpers
# ---------------------------------------------------------------------------

def move_to_pose(
    stm32_driver: Any,
    pose: dict[str, float],
) -> list[str]:
    """Move motors to *pose* using the STM32 driver.

    *pose* is a dict of ``{"x": <mm>, "y": <mm>}`` or
    ``{"x": <mm>, "y": <mm>, "z": <mm>}``.

    Returns a list of axes that were successfully moved.

    Raises ``ConnectionError`` if the driver is unavailable.
    Raises ``RuntimeError`` if any single-axis move fails.
    """
    if stm32_driver is None:
        raise ConnectionError("STM32 driver not available")

    moved: list[str] = []
    errors: list[str] = []

    # Retrieve current absolute positions so we can compute relative deltas.
    status = stm32_driver.get_motor_status()
    current_positions: dict[str, float] = status.get("positions", {})
    homed_axes = status.get("homed")

    for axis, target_mm in pose.items():
        axis_lower = axis.lower()
        current = current_positions.get(axis_lower, 0.0)
        delta = target_mm - current
        if isinstance(homed_axes, dict) and not homed_axes.get(axis_lower, False):
            errors.append(axis_lower)
            logger.error("move_to_pose: axis %s is not homed", axis_lower)
            continue
        if abs(delta) < 0.01:
            # Already at target; skip (not counted as moved)
            continue
        success = stm32_driver.move_motor(axis_lower, delta)
        if success:
            moved.append(axis_lower)
        else:
            errors.append(axis_lower)
            logger.error("move_to_pose: axis %s move failed", axis_lower)

    if errors:
        raise RuntimeError(f"Motor move failed for axes: {', '.join(errors)}")

    return moved


def read_lidar_distance(lidar_driver: Any) -> float | None:
    """Read a TF-Luna distance measurement.

    Returns the distance in mm, or ``None`` if the sensor is unavailable.
    """
    if lidar_driver is None:
        return None
    try:
        if not (lidar_driver.connected or lidar_driver.connect()):
            return None
        return lidar_driver.read_distance_mm()
    except Exception as exc:
        logger.warning("LiDAR read error in calibration_pose: %s", exc)
        return None
