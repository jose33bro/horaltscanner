"""
Camera Calibration Pose - automatic positioning and scan-pose memory.

Pose conventions
----------------
  X : centre / avance-recul du plateau (mm depuis le home)
  Y : rotation du plateau (mm depuis le home)
  Z : hauteur (mm depuis le home) — utilisé uniquement pour la Logitech USB

Camera-specific rules
---------------------
  Pi Camera  : X + Y only; Z is never touched.
  Logitech   : X + Y + Z.

The calibration poses are intentionally stored as simple dicts so they can
be overridden at runtime (e.g. persisted to config) without changing the
module API.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default calibration poses (mm from home position)
# These can be updated at runtime through `update_default_pose()`.
# ---------------------------------------------------------------------------

_DEFAULT_POSES: dict[str, dict[str, float]] = {
    "pi": {"x": 0.0, "y": 0.0},            # Z intentionally absent
    "usb": {"x": 0.0, "y": 0.0, "z": 50.0},  # Z = height for Logitech
}

# Expected TF-Luna distance (mm) at each camera's calibration pose.
# These are the distances from the LiDAR to the calibration target.
_LIDAR_EXPECTED_MM: dict[str, float] = {
    "pi": 300.0,
    "usb": 300.0,
}

# ---------------------------------------------------------------------------
# Saved scan poses – one per camera, keyed by camera name
# ---------------------------------------------------------------------------

_saved_poses: dict[str, dict[str, float]] = {}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_calibration_pose(camera: str) -> dict[str, float]:
    """Return the calibration pose for *camera* (copy)."""
    camera = camera.lower()
    if camera not in _DEFAULT_POSES:
        raise ValueError(f"Unknown camera '{camera}'. Supported: pi, usb")
    return dict(_DEFAULT_POSES[camera])


def update_default_pose(camera: str, pose: dict[str, float]) -> None:
    """Override the default calibration pose for *camera*."""
    camera = camera.lower()
    if camera not in _DEFAULT_POSES:
        raise ValueError(f"Unknown camera '{camera}'. Supported: pi, usb")
    _DEFAULT_POSES[camera] = {k: float(v) for k, v in pose.items()}


def save_scan_pose(camera: str, positions: dict[str, float]) -> dict[str, float]:
    """Save *positions* as the scan reference pose for *camera* and return it."""
    camera = camera.lower()
    _saved_poses[camera] = {k: float(v) for k, v in positions.items()}
    logger.info("Scan pose saved for %s: %s", camera, _saved_poses[camera])
    return dict(_saved_poses[camera])


def get_saved_scan_pose(camera: str) -> dict[str, float] | None:
    """Return the saved scan pose for *camera*, or None if not yet saved."""
    return dict(_saved_poses[camera]) if camera.lower() in _saved_poses else None


def clear_saved_pose(camera: str) -> None:
    """Remove the saved scan pose for *camera*."""
    _saved_poses.pop(camera.lower(), None)


# ---------------------------------------------------------------------------
# Motor movement helper
# ---------------------------------------------------------------------------


def move_to_pose(
    stm32_driver: Any,
    camera: str,
    *,
    lidar_driver: Any = None,
    lidar_tolerance_mm: float = 20.0,
) -> dict[str, Any]:
    """Move motors to the calibration pose for *camera*.

    Parameters
    ----------
    stm32_driver:
        The STM32Driver instance (must not be None).
    camera:
        ``"pi"`` or ``"usb"``.
    lidar_driver:
        Optional LidarDriver instance.  When connected, a distance reading is
        taken after positioning and compared against the expected distance from
        the Pi Camera or Logitech default.  The result is included in the
        return dict but **does not block or abort** the move.
    lidar_tolerance_mm:
        Maximum acceptable deviation between measured distance and the target
        pose's X coordinate (used as a proxy for distance to object).

    Returns
    -------
    dict with keys: camera, pose, lidar_distance_mm, lidar_ok, moves_done
    """
    pose = get_calibration_pose(camera)

    current = stm32_driver.get_motor_status().get("positions", {})
    moves_done: list[dict[str, float]] = []

    for axis in ("x", "y", "z"):
        if axis not in pose:
            # Pi Camera: skip Z entirely
            continue
        target = pose[axis]
        current_pos = current.get(axis, 0.0)
        delta = target - current_pos
        if abs(delta) > 0.001:  # avoid no-op moves
            ok = stm32_driver.move_motor(axis.upper(), delta)
            if not ok:
                raise RuntimeError(
                    f"Motor move failed for axis {axis.upper()} (delta={delta:.2f} mm)"
                )
            moves_done.append({axis: delta})
            logger.info("Moved %s by %.2f mm to reach %.2f mm", axis.upper(), delta, target)

    result: dict[str, Any] = {
        "camera": camera,
        "pose": pose,
        "moves_done": moves_done,
        "lidar_distance_mm": None,
        "lidar_ok": None,
    }

    # Optional TF-Luna validation
    if lidar_driver is not None and lidar_driver.connected:
        dist = lidar_driver.read_distance_mm()
        result["lidar_distance_mm"] = dist
        if dist is not None:
            expected_dist = _LIDAR_EXPECTED_MM.get(camera, 300.0)
            within = abs(dist - expected_dist) <= lidar_tolerance_mm
            result["lidar_ok"] = within
            if not within:
                logger.warning(
                    "LiDAR distance %.1f mm deviates from expected %.1f mm "
                    "(tolerance ±%.1f mm) for %s camera",
                    dist,
                    expected_dist,
                    lidar_tolerance_mm,
                    camera,
                )
        else:
            result["lidar_ok"] = False

    return result
