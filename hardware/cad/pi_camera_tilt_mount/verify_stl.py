#!/usr/bin/env python3
"""Verify the printable STL files: closed manifold mesh, no degenerate
triangles, expected bounding box and positive volume.

Usage (from the repo root):
    python3 hardware/cad/pi_camera_tilt_mount/verify_stl.py

Only needs numpy. Exits non-zero if any file fails.
"""
from __future__ import annotations

import struct
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
REPO_ROOT = HERE.parents[2]
WELD_DECIMALS = 4  # vertices closer than 0.0001 mm are the same vertex
DEGENERATE_AREA_MM2 = 1e-6
BBOX_TOLERANCE_MM = 0.05

# filename -> expected bounding box extents (x, y, z) in mm
EXPECTED_EXTENTS = {
    HERE / "stl" / "pi_camera_tilt_base.stl": (30.45, 27.20, 43.20),
    HERE / "stl" / "fit_test_rear_cavity_30.45x38.2.stl": (30.45, 3.20, 38.20),
    HERE / "stl" / "adjustment_rod_M5x50_ball6.5_square_m3.stl": (6.50, 6.50, 60.50),
    HERE / "stl" / "wheel_crank_50mm_square_m3.stl": (50.00, 50.00, 11.00),
    HERE / "stl" / "camera_carrier_plate_v4_onepiece.stl": (25.50, 8.29, 35.00),
    HERE / "stl" / "camera_front_cover_v3_clip.stl": (25.50, 4.56, 24.50),
    HERE / "stl" / "ball_screw_M5x40_ball6.5.stl": (6.50, 6.50, 42.50),
}


def load_stl(path: Path) -> np.ndarray:
    """Return triangles as an (n, 3, 3) float array (binary or ASCII STL)."""
    data = path.read_bytes()
    if len(data) >= 84:
        count = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * count == len(data):
            dtype = np.dtype(
                [("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")]
            )
            return np.frombuffer(data, dtype=dtype, count=count, offset=84)["v"].astype(
                np.float64
            )
    verts = []
    for line in data.decode("ascii", "replace").splitlines():
        parts = line.split()
        if parts and parts[0] == "vertex":
            verts.append([float(p) for p in parts[1:4]])
    return np.array(verts, dtype=np.float64).reshape(-1, 3, 3)


def analyse(tris: np.ndarray) -> dict:
    flat = np.round(tris.reshape(-1, 3), WELD_DECIMALS)
    _, inverse = np.unique(flat, axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    degenerate = (
        (areas < DEGENERATE_AREA_MM2)
        | (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 0] == faces[:, 2])
    )
    # Orientation-aware edge check: in a closed, consistently oriented
    # manifold every directed edge appears once and its reverse once.
    directed = Counter()
    for a, b, c in faces[~degenerate]:
        directed[(a, b)] += 1
        directed[(b, c)] += 1
        directed[(c, a)] += 1
    bad_edges = sum(
        1
        for (a, b), n in directed.items()
        if n != 1 or directed.get((b, a), 0) != 1
    )
    volume = float(np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum() / 6)
    extents = tris.reshape(-1, 3).max(axis=0) - tris.reshape(-1, 3).min(axis=0)
    return {
        "triangles": len(tris),
        "degenerate": int(degenerate.sum()),
        "bad_edges": bad_edges,
        "volume": volume,
        "extents": extents,
    }


def check_header(path: Path) -> list[str]:
    """Binary STL header must carry the material and not look like ASCII."""
    data = path.read_bytes()
    if len(data) < 84:
        return ["file too short"]
    header = data[:80]
    errors = []
    if header.lstrip().lower().startswith(b"solid"):
        errors.append("header starts with 'solid' (ambiguous with ASCII STL)")
    if b"Creality Hyper PLA blanc" not in header:
        errors.append("header lacks material 'Creality Hyper PLA blanc'")
    if 84 + 50 * struct.unpack("<I", data[80:84])[0] != len(data):
        errors.append("not a valid binary STL")
    return errors


def main() -> int:
    failed = False
    for path in sorted((HERE / "stl").glob("*.stl")):
        errors = check_header(path)
        print(f"{'FAIL' if errors else 'OK  '} header {path.name}"
              + (f"  <- {'; '.join(errors)}" if errors else ""))
        failed |= bool(errors)
    for path, expected in EXPECTED_EXTENTS.items():
        if not path.exists():
            print(f"MISSING  {path.name}")
            failed = True
            continue
        info = analyse(load_stl(path))
        errors = []
        if info["degenerate"]:
            errors.append(f"{info['degenerate']} degenerate triangles")
        if info["bad_edges"]:
            errors.append(f"{info['bad_edges']} non-manifold/open edges")
        if info["volume"] <= 0:
            errors.append("non-positive volume (inverted or open)")
        if np.any(np.abs(info["extents"] - np.array(expected)) > BBOX_TOLERANCE_MM):
            errors.append(
                f"bbox {np.round(info['extents'], 2).tolist()} != expected {list(expected)}"
            )
        status = "FAIL" if errors else "OK  "
        failed |= bool(errors)
        print(
            f"{status} {path.name}: {info['triangles']} tris, "
            f"bbox {np.round(info['extents'], 2).tolist()}, vol {info['volume']:.1f} mm3"
            + (f"  <- {'; '.join(errors)}" if errors else "")
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
