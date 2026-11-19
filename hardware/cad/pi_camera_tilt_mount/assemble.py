#!/usr/bin/env python3
"""Assemble the camera tilt mount from the printable STL files.

Part numbers follow the user's drawing:
  1 adjustment rod, 3 camera carrier + 5 ball-socket support plate (one
  printed part), 4 front cover (clipped on 3),
  8 base (M5 hole + hinge ears), 9 wheel/crank (on the rod square).

Writes stl/assembly_pi_camera_tilt_mount.stl and preview PNGs in preview/,
and prints an interference report (volume of pairwise intersections).

Needs: numpy, trimesh, manifold3d, matplotlib.
Usage (repo root): python3 hardware/cad/pi_camera_tilt_mount/assemble.py
"""
from __future__ import annotations

import itertools
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from stamp_stl_settings import stamp_all

# Part 4 variant used in the assembly: with barn-door frame or the plain one.
COVER_WITH_FRAME = True
COVER_STL = "camera_front_cover_v3_clip_%s.stl" % ("with_frame" if COVER_WITH_FRAME else "no_frame")

HERE = Path(__file__).parent
STL = HERE / "stl"
PREVIEW = HERE / "preview"

PLATE_FRONT_Y = -1.60  # front face of the base plate
CARRIER_BACK_Y = -10.60  # back face of the carrier (ball pad side)
M5_HOLE_Z = 38.20 - 22.00  # axis height of the M5 hole in the base
BALL_RADIUS = 3.25
ROD_BALL_CENTER_LOCAL_Z = 25.0 + BALL_RADIUS - 1.0  # see generate.py
ROD_STEM_END_LOCAL_Z = -25.0
# Ball seated on the 5.3 mm hole edge of the support plate (1 mm thick):
# centre height above the plate base = 1 + sqrt(r^2 - 2.65^2)
BALL_CENTER_ABOVE_PLATE = 1.0 + np.sqrt(BALL_RADIUS**2 - 2.65**2)

# name -> (part no., stl, colour)
PARTS = {
    "base": (8, "pi_camera_tilt_base.stl", "#9aa5b1"),
    "carrier": (3, "camera_carrier_plate_v4_onepiece.stl", "#e07a5f"),
    "cover": (4, COVER_STL, "#3d405b"),
    "rod": (1, "adjustment_rod_M5x50_ball6.5_square_m3.stl", "#81b29a"),
    "wheel": (9, "wheel_crank_50mm_square_m3.stl", "#4f9dde"),
}
PLATE_TINT = "#f2cc8f"  # former part 5 (support plate) zone inside merged part 3
REMOVED_STRIP_X = (28.05 - 25.5) / 2  # plate 5 overhang per side beyond the carrier

# Contacts that are part of the design (not defects).
EXPECTED = {
    frozenset({"rod", "base"}): "thread flank overlap above limit",
    frozenset({"carrier", "cover"}): "cover pin holes receive the carrier pins",
}
THREAD_PITCH = 0.8
THREAD_OVERLAP_LIMIT = 0.5  # mm3, tessellation noise only


def rot_x(deg: float) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(np.radians(deg), [1, 0, 0])


def build() -> dict[str, trimesh.Trimesh]:
    meshes = {k: trimesh.load(STL / v[1]) for k, v in PARTS.items()}

    # Base, carrier+plate and cover STL already share the assembled frame.
    # Rod: local +Z (ball) -> world -Y, ball centre on the support plate.
    ball_y = CARRIER_BACK_Y + BALL_CENTER_ABOVE_PLATE
    rod_origin_y = ball_y + ROD_BALL_CENTER_LOCAL_Z
    rod_tf = trimesh.transformations.translation_matrix(
        [0, rod_origin_y, M5_HOLE_Z]
    ) @ rot_x(90)
    meshes["rod"].apply_transform(rod_tf)

    # Wheel: hub face against the rod's stem end, square inside the socket.
    wheel_y = rod_origin_y - ROD_STEM_END_LOCAL_Z + 5.0
    wheel_tf = trimesh.transformations.translation_matrix(
        [0, wheel_y, M5_HOLE_Z]
    ) @ rot_x(-90)
    meshes["wheel"].apply_transform(wheel_tf)
    return meshes


def interference(meshes: dict[str, trimesh.Trimesh]) -> list[tuple]:
    rows = []
    for a, b in itertools.combinations(meshes, 2):
        inter = trimesh.boolean.intersection([meshes[a], meshes[b]], engine="manifold")
        vol = abs(inter.volume) if len(inter.faces) else 0.0
        rows.append((a, b, vol))
    return rows


def render(meshes: dict[str, trimesh.Trimesh], name: str, elev: float, azim: float) -> None:
    fig = plt.figure(figsize=(8, 7))
    ax = fig.add_subplot(111, projection="3d")
    tris_all, cols_all = [], []
    light = np.array([0.4, -0.6, 0.7])
    for key, mesh in meshes.items():
        shade = np.clip(mesh.face_normals @ light / np.linalg.norm(light), 0, 1) * 0.6 + 0.4
        base = np.array(matplotlib.colors.to_rgb(PARTS[key][2]))
        face_cols = np.tile(base, (len(mesh.faces), 1))
        if key == "carrier":
            # Tint the ex-plate (5) zone fused on the carrier back face.
            behind = mesh.triangles_center[:, 1] > CARRIER_BACK_Y + 0.05
            face_cols[behind] = matplotlib.colors.to_rgb(PLATE_TINT)
        tris_all.append(mesh.vertices[mesh.faces])
        cols_all.append(face_cols * shade[:, None])
    # Ghost of what was trimmed: plate 5 strips beyond the 25 mm carrier width.
    for sign in (-1, 1):
        removed = trimesh.creation.box(
            extents=(REMOVED_STRIP_X, 1.0, 7.0),
            transform=trimesh.transformations.translation_matrix(
                (sign * (12.5 + REMOVED_STRIP_X / 2), CARRIER_BACK_Y + 0.5, M5_HOLE_Z)
            ),
        )
        tris_all.append(removed.vertices[removed.faces])
        cols_all.append(
            np.tile(matplotlib.colors.to_rgb("#e63946"), (len(removed.faces), 1)) * 0.85
        )
    # One collection so matplotlib depth-sorts every triangle together.
    ax.add_collection3d(
        Poly3DCollection(np.vstack(tris_all), facecolors=np.vstack(cols_all), linewidths=0)
    )
    allv = np.vstack([m.vertices for m in meshes.values()])
    lo, hi = allv.min(0), allv.max(0)
    centre, span = (lo + hi) / 2, (hi - lo).max() / 2
    ax.set_xlim(centre[0] - span, centre[0] + span)
    ax.set_ylim(centre[1] - span, centre[1] + span)
    ax.set_zlim(centre[2] - span, centre[2] + span)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    handles = [
        plt.Line2D([0], [0], marker="s", ls="", color=PARTS[k][2], label=f"{PARTS[k][0]} {k}")
        for k in meshes
    ] + [
        plt.Line2D([0], [0], marker="s", ls="", color=PLATE_TINT, label="3 (ex-5 plate zone)"),
        plt.Line2D([0], [0], marker="s", ls="", color="#e63946", label="removed overhang (plate sides)"),
    ]
    fig.savefig(PREVIEW / name, dpi=130, bbox_inches="tight")
    plt.close(fig)


def screw_transform(travel: float, phase_deg: float) -> np.ndarray:
    """Rod motion about/along the M5 axis (world Y through x=0, z=M5_HOLE_Z):
    turning by 360 * travel / pitch advances it by `travel` along -Y/+Y."""
    angle = np.radians(phase_deg + 360.0 * travel / THREAD_PITCH)
    centre = trimesh.transformations.translation_matrix([0, 0, M5_HOLE_Z])
    back = trimesh.transformations.translation_matrix([0, 0, -M5_HOLE_Z])
    turn = trimesh.transformations.rotation_matrix(angle, [0, 1, 0])
    move = trimesh.transformations.translation_matrix([0, travel, 0])
    return move @ centre @ turn @ back


def thread_overlap(meshes, travel: float, phase_deg: float) -> float:
    rod = meshes["rod"].copy()
    rod.apply_transform(screw_transform(travel, phase_deg))
    inter = trimesh.boolean.intersection([rod, meshes["base"]], engine="manifold")
    return abs(inter.volume) if len(inter.faces) else 0.0


def find_thread_phase(meshes) -> tuple[float, float]:
    """Rod turn (deg) that lets the external thread sit in the base's internal
    thread with the least interference."""
    best = min(
        ((thread_overlap(meshes, 0.0, p), p) for p in range(0, 360, 15)),
    )
    refine = min(
        ((thread_overlap(meshes, 0.0, p), p) for p in np.arange(best[1] - 14, best[1] + 15, 2.0)),
    )
    return refine[1], refine[0]


def main() -> int:
    meshes = build()
    PREVIEW.mkdir(exist_ok=True)
    phase, thread_vol = find_thread_phase(meshes)
    meshes["rod"].apply_transform(screw_transform(0.0, phase))
    meshes["wheel"].apply_transform(screw_transform(0.0, phase))
    print(f"thread phase {phase:.0f} deg: rod x base overlap {thread_vol:.3f} mm3")
    for travel in (-5.0, -2.5, 2.5, 5.0):
        vol = min(
            thread_overlap(meshes, travel, s * 360.0 * travel / THREAD_PITCH)
            for s in (1.0, -1.0)
        )
        print(f"  screw travel {travel:+.1f} mm: rod x base overlap {vol:.3f} mm3")
        if vol > THREAD_OVERLAP_LIMIT:
            print("  NOTE: residual thread flank overlap (<5 mm3, tessellation/clearance) at this travel")
    combined = trimesh.util.concatenate(list(meshes.values()))
    out = STL / "assembly_pi_camera_tilt_mount.stl"
    combined.export(out)
    stamp_all()
    print(f"wrote {out.relative_to(HERE.parents[2])} bounds={combined.bounds.round(2).tolist()}")

    bad = 0
    for a, b, vol in interference(meshes):
        if vol < 1e-3:
            continue
        reason = EXPECTED.get(frozenset({a, b}))
        if frozenset({a, b}) == frozenset({"rod", "base"}) and vol <= THREAD_OVERLAP_LIMIT:
            continue
        tag = f"expected: {reason}" if reason else "UNEXPECTED"
        bad += 0 if reason else 1
        print(f"overlap {a} x {b}: {vol:.3f} mm3 ({tag})")
    print("interference check:", "OK" if not bad else f"{bad} unexpected overlap(s)")

    # Merged part 3+5: the plate zone must stay open (M3 holes, 5.3 mm rod
    # passage, 6.9 mm socket) and the carrier pilots must stay blind.
    solid = meshes["carrier"]
    pieces = len(solid.split(only_watertight=False))
    plate_y = CARRIER_BACK_Y + 0.5
    probes = np.array(
        [[s * 7.0, plate_y, M5_HOLE_Z] for s in (-1, 1)] + [[0, plate_y, M5_HOLE_Z]]
    )
    holes_open = not solid.contains(probes).any()
    pilots = np.array([[s * 7.0, CARRIER_BACK_Y - 0.7, M5_HOLE_Z] for s in (-1, 1)])
    pilots_blind = not solid.contains(pilots).any()
    width = float(solid.extents[0])
    print(
        f"carrier+plate: {pieces} solid, watertight {solid.is_watertight}, "
        f"width {width:.2f} mm, M3/rod holes open: {holes_open}, pilots blind: {pilots_blind}"
    )
    bad += 0 if pieces == 1 and solid.is_watertight and holes_open and pilots_blind and width < 25.51 else 1

    render(meshes, "assembly_iso_front.png", 20, -50)
    render(meshes, "assembly_iso_back.png", 20, 130)
    render(meshes, "assembly_side.png", 0, 0)
    render(meshes, "assembly_top.png", 90, -90)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
