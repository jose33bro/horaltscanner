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
    HERE / "stl" / "adjustment_rod_M10x50_ball6.5_square_m3.stl": (10.00, 10.00, 60.50),
    HERE / "stl" / "wheel_crank_50mm_square_m3.stl": (50.00, 50.00, 11.00),
    HERE / "stl" / "camera_carrier_plate_v4_onepiece.stl": (25.50, 10.75, 35.00),
    HERE / "stl" / "camera_front_cover_v3_clip_no_frame.stl": (28.24, 9.58, 24.50),
    HERE / "stl" / "camera_front_cover_v3_clip_with_frame.stl": (28.24, 16.66, 24.50),
    HERE / "stl" / "camera_barn_door_x_x2.stl": (10.00, 19.00, 0.90),
    HERE / "stl" / "camera_barn_door_z_x2.stl": (20.00, 10.00, 0.90),
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


def check_lens_square() -> list[str]:
    import generate as g

    import trimesh

    # Measured on the no_frame cover STL (z up, front face = min y). Reference:
    # PCB connector edge = lower pin-hole row z - 2.0 mm (drawing assumption),
    # far (hole-side) edge = connector edge + 24.16 mm.
    mesh = trimesh.load(HERE / "stl" / "camera_front_cover_v3_clip_no_frame.stl")
    y0 = float(mesh.bounds[0][1])
    zs = np.arange(mesh.bounds[0][2] + 0.01, mesh.bounds[1][2], 0.01)

    def empty_runs(x: float, y: float) -> list[tuple[float, float]]:
        inside = mesh.contains(np.array([[x, y, z] for z in zs]))
        runs, start = [], None
        for z, solid in zip(zs, inside):
            if not solid and start is None:
                start = z
            elif solid and start is not None:
                runs.append((start, z))
                start = None
        return runs

    hole_runs = [r for r in empty_runs(10.5, y0 + g.COVER_THICKNESS + g.COVER_FRONT_PAD - 0.5)
                 if r[1] - r[0] < 4.0]
    if len(hole_runs) != 2:
        print(f"FAIL cannot find the 2 pin holes at x=10.5: {hole_runs}")
        return ["pin holes"]
    conn_edge_z = (hole_runs[0][0] + hole_runs[0][1]) / 2 - g.CAM_HOLE_ROW_FROM_CONNECTOR_EDGE
    far_edge_z = conn_edge_z + g.CAM_PCB_HEIGHT
    recess = [r for r in empty_runs(g.LENS_HOLE_DIAMETER / 2 + 0.6, y0 + 3.0)
              if r[1] - r[0] > 5.0]
    if len(recess) != 1:
        print(f"FAIL cannot isolate the square recess: {recess}")
        return ["recess"]
    conn = recess[0][0] - float(mesh.bounds[0][2])  # from the cover's connector-side (bottom) edge
    far = float(mesh.bounds[1][2]) - recess[0][1]
    if not (mesh.bounds[0][2] + 1.0 < recess[0][0] and recess[0][1] < mesh.bounds[1][2]):
        print('FAIL recess leaves the cover')
        return ['recess bounds']
    print(f"     recess z {recess[0][0]:.2f}..{recess[0][1]:.2f} (size "
          f"{recess[0][1] - recess[0][0]:.2f}), PCB edges z {conn_edge_z:.2f}/{far_edge_z:.2f}")
    errs = []
    wall = g.COVER_THICKNESS + g.COVER_FRONT_PAD - g.LENS_RECESS_DEPTH
    ring = g.COVER_RECESS_Z / 2 - g.COVER_LENS_HOLE_DIAMETER / 2 - g.COVER_LENS_RISE
    for name, got, want in (("front wall", wall, 1.2), ("lateral ring", ring, 0.0)):
        ok = got >= want - 1e-6 and (name != "lateral ring" or got > 0)
        print(f"{'OK  ' if ok else 'FAIL'} cover {name}: {got:.2f} mm (min {want})")
        if not ok:
            errs.append(name)
    for name, got, want in (("connector edge", conn, g.COVER_RECESS_BOTTOM_FROM_EDGE), ("far edge", far, g.COVER_LENGTH_Z - g.COVER_RECESS_BOTTOM_FROM_EDGE - g.COVER_RECESS_Z), ("recess size Z", recess[0][1] - recess[0][0], g.COVER_RECESS_Z)):
        ok = abs(got - want) <= 0.2
        print(f"{'OK  ' if ok else 'FAIL'} lens square {name}: {got:.2f} mm (user {want})")
        if not ok:
            errs.append(name)
    back = y0 + g.COVER_THICKNESS + g.COVER_FRONT_PAD
    zc = (recess[0][0] + recess[0][1]) / 2
    xs = np.arange(0.0, 9.0, 0.01)
    xin = mesh.contains(np.array([[x, y0 + 3.0, zc] for x in xs]))
    half = float(xs[xin][0])
    ok = abs(2 * half - g.LENS_RECESS_WIDTH_X) <= 0.05 and abs(2 * half - 14.00) <= 0.05
    print(f'{"OK  " if ok else "FAIL"} lens square width X measured {2 * half:.2f} mm (14.00)')
    if not ok:
        errs.append('square width X')
    zb = float(mesh.bounds[0][2])
    probes = (
        ('notch empty (x0,z34,front wall)', (0.0, y0 + 0.6, zb + 26.5), False),
        ('notch empty (x+2.4,z34,mid)', (2.4, y0 + 3.0, zb + 26.5), False),
        ('beside notch solid (x3.5,z30)', (3.5, y0 + 3.0, zb + 22.5), True),
        ('recess depth 5.62 (back-5.5 empty)', (5.0, back - 5.5, zb + 8.0), False),
        ('front wall solid (back-5.7)', (5.0, back - 5.7, zb + 8.0), True),
        ('relief 3.5 deep empty (z 20)', (0.0, back - 3.4, zb + 20.0), False),
        ('relief floor solid (z 20)', (0.0, back - 3.6, zb + 20.0), True),
    )
    for name, p, want in probes:
        got = bool(mesh.contains(np.array([p]))[0])
        ok = got == want
        print(f'{"OK  " if ok else "FAIL"} cover {name}')
        if not ok:
            errs.append(name)
    wz = np.arange(recess[0][0] - 0.5, recess[0][1] + 0.5, 0.01)
    wi = mesh.contains(np.array([[0.0, y0 + 0.5, z] for z in wz]))
    hz = wz[~wi]
    wx = np.arange(-8.0, 8.0, 0.01)
    xi = mesh.contains(np.array([[x, y0 + 0.5, (hz.min() + hz.max()) / 2] for x in wx]))
    hx = wx[~xi]
    dz = (hz.min() + hz.max()) / 2 - zc
    dx = (hx.min() + hx.max()) / 2
    ring = min(hz.min() - recess[0][0], recess[0][1] - hz.max(), 6.83 - (hx.max() - hx.min()) / 2 if False else 9)
    ok = abs(dz) <= 0.03 and abs(dx) <= 0.03
    print(f'{"OK  " if ok else "FAIL"} lens window centre x {dx:.2f}, z {(hz.min() + hz.max()) / 2:.2f} vs square z {zc:.2f}; dia {hx.max() - hx.min():.2f}; Z ring {min(hz.min() - recess[0][0], recess[0][1] - hz.max()):.2f}')
    if not ok:
        errs.append('window centred')
    width = float(mesh.extents[0])
    ok = abs(width - 28.24) <= 0.01
    print(f'{"OK  " if ok else "FAIL"} cover width {width:.2f} mm (28.24)')
    if not ok:
        errs.append('width')
    return errs


def check_base_thread_hole() -> list[str]:
    import trimesh

    base = trimesh.load(HERE / "stl" / "pi_camera_tilt_base.stl")
    z0 = 38.2 - 22.0
    sec = base.section(plane_origin=[0, -0.5, 0], plane_normal=[0, 1, 0])
    pts = sec.vertices
    r = np.hypot(pts[:, 0], pts[:, 2] - z0)
    r_min = r[r < 7].min()
    printed_dia = 2 * r_min * 0.976
    errs = []
    if abs(2 * r_min - 8.4) > 0.1:
        errs.append(f"base thread hole crest dia {2 * r_min:.2f} != 8.40")
    if printed_dia < 6.5 + 0.4:
        errs.append(f"base hole {printed_dia:.2f} mm after shrink < 6.9 (ball 6.5 + 0.4)")
    print(f"{'OK  ' if not errs else 'FAIL'} base M10 hole crest dia {2 * r_min:.2f} mm ({printed_dia:.2f} printed)")
    return errs


def check_assembly() -> list[str]:
    import trimesh

    car = trimesh.load(HERE / 'stl' / 'camera_carrier_plate_v4_onepiece.stl')
    errs = []
    for name in ('no_frame', 'with_frame'):
        cov = trimesh.load(HERE / 'stl' / f'camera_front_cover_v3_clip_{name}.stl')
        lo, hi = cov.bounds
        pts = car.sample(60000)
        pts = pts[np.all((pts > lo) & (pts < hi), axis=1)]
        hit = int(cov.contains(pts).sum()) if len(pts) else 0
        ok = hit == 0
        print(f'{"OK  " if ok else "FAIL"} assembly 3+5 vs cover {name}: {hit} carrier sample points inside the cover')
        if not ok:
            errs.append(name)
    return errs


def main() -> int:
    failed = bool(check_lens_square()) or bool(check_assembly()) or bool(check_base_thread_hole())
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
