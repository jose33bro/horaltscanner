#!/usr/bin/env python3
"""Assemble the camera tilt mount from the printable STL files.

Part numbers follow the user's drawing:
  1 adjustment rod, 3 camera carrier, 4 front cover (clipped on 3),
  5 ball-socket support plate (snapped on the rod ball, resting on 3),
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
    "carrier": (3, "camera_carrier_v3_25x24_tab4.8.stl", "#e07a5f"),
    "cover": (4, "camera_front_cover_v3_clip.stl", "#3d405b"),
    "rod": (1, "adjustment_rod_M5x50_ball6.5_square_m3.stl", "#81b29a"),
    "support_plate": (5, "camera_support_plate_28.05x7x1.stl", "#f2cc8f"),
    "wheel": (9, "wheel_crank_50mm_square_m3.stl", "#4f9dde"),
}

# Contacts that are part of the design (not defects).
EXPECTED = {
    frozenset({"rod", "base"}): "printed M5 thread cuts into the 5 mm pilot hole",
    frozenset({"carrier", "cover"}): "cover pins press-fit in the carrier holes",
}


def rot_x(deg: float) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(np.radians(deg), [1, 0, 0])


def build() -> dict[str, trimesh.Trimesh]:
    meshes = {k: trimesh.load(STL / v[1]) for k, v in PARTS.items()}

    # Base, carrier and cover STL already share the assembled frame.
    # Rod: local +Z (ball) -> world -Y, ball centre on the support plate.
    ball_y = CARRIER_BACK_Y + BALL_CENTER_ABOVE_PLATE
    rod_origin_y = ball_y + ROD_BALL_CENTER_LOCAL_Z
    rod_tf = trimesh.transformations.translation_matrix(
        [0, rod_origin_y, M5_HOLE_Z]
    ) @ rot_x(90)
    meshes["rod"].apply_transform(rod_tf)

    # Support plate: base on the carrier back, petals toward +Y (Rx(-90)).
    plate_tf = trimesh.transformations.translation_matrix(
        [0, CARRIER_BACK_Y, M5_HOLE_Z]
    ) @ rot_x(-90)
    meshes["support_plate"].apply_transform(plate_tf)

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
        tris_all.append(mesh.vertices[mesh.faces])
        cols_all.append(base * shade[:, None])
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
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=8)
    fig.savefig(PREVIEW / name, dpi=130, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    meshes = build()
    PREVIEW.mkdir(exist_ok=True)
    combined = trimesh.util.concatenate(list(meshes.values()))
    out = STL / "assembly_pi_camera_tilt_mount.stl"
    combined.export(out)
    print(f"wrote {out.relative_to(HERE.parents[2])} bounds={combined.bounds.round(2).tolist()}")

    bad = 0
    for a, b, vol in interference(meshes):
        if vol < 1e-3:
            continue
        reason = EXPECTED.get(frozenset({a, b}))
        tag = f"expected: {reason}" if reason else "UNEXPECTED"
        bad += 0 if reason else 1
        print(f"overlap {a} x {b}: {vol:.3f} mm3 ({tag})")
    print("interference check:", "OK" if not bad else f"{bad} unexpected overlap(s)")

    # Plate 5 <-> carrier 3: flush contact, M3 holes aligned with carrier pilots.
    plate, carrier = meshes["support_plate"], meshes["carrier"]
    contact = float(np.abs(plate.bounds[0][1] - CARRIER_BACK_Y))
    probes = np.array([[s * 7.0, CARRIER_BACK_Y - 0.7, M5_HOLE_Z] for s in (-1, 1)])
    hole_ok = not carrier.contains(probes).any() and not plate.contains(
        probes + [0, 1.2, 0]
    ).any()
    print(f"plate 5 on carrier 3: gap {contact:.3f} mm, M3 holes aligned: {hole_ok}")
    bad += 0 if contact < 0.01 and hole_ok else 1

    render(meshes, "assembly_iso_front.png", 20, -50)
    render(meshes, "assembly_iso_back.png", 20, 130)
    render(meshes, "assembly_side.png", 0, 0)
    render(meshes, "assembly_top.png", 90, -90)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
