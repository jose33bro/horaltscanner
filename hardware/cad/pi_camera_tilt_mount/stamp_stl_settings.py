#!/usr/bin/env python3
"""Write the print settings from print_settings.json into the 80-byte
header of every STL (files are rewritten as binary STL, geometry unchanged).

Usage: python3 hardware/cad/pi_camera_tilt_mount/stamp_stl_settings.py
Only needs numpy. generate.py and assemble.py call stamp_all() after export.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
STL_DIR = HERE / "stl"
SETTINGS = HERE / "print_settings.json"
HEADER_BYTES = 80
MATERIAL = "Creality Hyper PLA blanc"

_DTYPE = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])


def read_triangles(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if len(data) >= 84:
        count = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * count == len(data):
            return np.frombuffer(data, dtype=_DTYPE, count=count, offset=84).copy()
    verts = []
    for line in data.decode("ascii", "replace").splitlines():
        parts = line.split()
        if parts and parts[0] == "vertex":
            verts.append([float(p) for p in parts[1:4]])
    v = np.array(verts, dtype="<f4").reshape(-1, 3, 3)
    tris = np.zeros(len(v), dtype=_DTYPE)
    tris["v"] = v
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    norm = np.linalg.norm(n, axis=1, keepdims=True)
    tris["n"] = np.divide(n, norm, out=np.zeros_like(n), where=norm > 0)
    return tris


def build_header(part: dict, common: dict) -> bytes:
    if part.get("printable", True):
        text = (
            f"{MATERIAL};N{common['nozzle_mm']} L{part['layer_height_mm']} "
            f"I{part['infill_percent']}% W{part['walls']} "
            f"T{common['nozzle_temp_c']}/B{common['bed_temp_c']} "
            f"V{part['speed_mm_s']};{part['header_orientation']}"
        )
    else:
        text = f"{MATERIAL};{part['header_orientation']}"
    raw = text.encode("ascii")
    if len(raw) > HEADER_BYTES:
        raise ValueError(f"header too long ({len(raw)} > {HEADER_BYTES}): {text}")
    return raw.ljust(HEADER_BYTES, b" ")


def stamp_all() -> None:
    cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
    for name, part in cfg["parts"].items():
        path = STL_DIR / name
        if not path.exists():
            raise FileNotFoundError(path)
        tris = read_triangles(path)
        header = build_header(part, cfg["common"])
        path.write_bytes(header + struct.pack("<I", len(tris)) + tris.tobytes())
        print(f"stamped {name}: {header.decode().rstrip()}")


if __name__ == "__main__":
    stamp_all()
    sys.exit(0)
