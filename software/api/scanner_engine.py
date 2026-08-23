"""
Scanner Engine - 3D reconstruction (point cloud → mesh → STL/AMF)
Uses Open3D when available; falls back to a stub otherwise.
"""

import io
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import open3d as o3d
    _O3D_AVAILABLE = True
except ImportError:
    _O3D_AVAILABLE = False
    logger.warning("Open3D not available; reconstruction will return stubs")


# ---------------------------------------------------------------------------
# Point Cloud Store (accumulated during a scan)
# ---------------------------------------------------------------------------

@dataclass
class ScanData:
    points: List[List[float]] = field(default_factory=list)   # [[x,y,z], ...]
    colors: List[List[float]] = field(default_factory=list)   # [[r,g,b], ...]  0–1

    def add_point(self, x: float, y: float, z: float,
                  r: float = 0.5, g: float = 0.5, b: float = 0.5) -> None:
        self.points.append([x, y, z])
        self.colors.append([r, g, b])

    def point_count(self) -> int:
        return len(self.points)

    def clear(self) -> None:
        self.points.clear()
        self.colors.clear()

    def as_dict(self) -> dict:
        return {
            "points": self.points,
            "colors": self.colors,
            "count": len(self.points),
        }


# ---------------------------------------------------------------------------
# Scan Session
# ---------------------------------------------------------------------------

class ScanSession:
    """Manages a live scan session (background thread accumulates points)."""

    def __init__(self):
        self._data = ScanData()
        self._lock = threading.Lock()
        self._scanning = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0
        self._quality: float = 0.0

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._scanning:
                return
            self._data.clear()
            self._scanning = True
            self._start_time = time.time()
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
        logger.info("Scan started")

    def stop(self) -> None:
        with self._lock:
            self._scanning = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("Scan stopped – %d points captured", self._data.point_count())

    def _capture_loop(self) -> None:
        """Background loop: generate simulated or real point cloud data."""
        angle = 0.0
        while True:
            with self._lock:
                if not self._scanning:
                    break
            # In a real system this would call camera_driver + lidar_driver
            # and compute triangulated 3D coordinates.  Here we generate a
            # synthetic sphere so the UI has something to render.
            r = 50.0
            x = r * np.cos(np.radians(angle))
            z_val = r * np.sin(np.radians(angle))
            for height in np.linspace(-30, 30, 5):
                with self._lock:
                    self._data.add_point(
                        x + np.random.uniform(-1, 1),
                        float(height) + np.random.uniform(-0.5, 0.5),
                        z_val + np.random.uniform(-1, 1),
                        r=0.6, g=0.8, b=0.9,
                    )
            angle = (angle + 2) % 360
            n = self._data.point_count()
            self._quality = min(1.0, n / 5000) * 100
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Status / data
    # ------------------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            elapsed = time.time() - self._start_time if self._scanning else 0.0
            return {
                "scanning": self._scanning,
                "points": self._data.point_count(),
                "elapsed_s": round(elapsed, 1),
                "quality": round(self._quality, 1),
            }

    def get_pointcloud(self) -> dict:
        with self._lock:
            return self._data.as_dict()


# ---------------------------------------------------------------------------
# 3D Reconstruction
# ---------------------------------------------------------------------------

class ReconstructionEngine:
    """Converts a ScanData point cloud into a mesh and exports STL/AMF."""

    def __init__(self, scan_session: ScanSession):
        self._session = scan_session
        self._last_stl: Optional[bytes] = None
        self._last_amf: Optional[bytes] = None

    def reconstruct(self) -> dict:
        """Run Poisson surface reconstruction.  Returns {ok, stl_size, amf_size, error}."""
        pc_dict = self._session.get_pointcloud()
        points = pc_dict.get("points", [])

        if len(points) < 100:
            return {"ok": False, "stl_size": 0, "amf_size": 0,
                    "error": f"Not enough points ({len(points)} < 100)"}

        if not _O3D_AVAILABLE:
            # Return stub files so the rest of the pipeline can be exercised
            self._last_stl = b"solid stub\nendsolid stub\n"
            self._last_amf = b'<?xml version="1.0"?><amf></amf>'
            return {
                "ok": True,
                "stl_size": len(self._last_stl),
                "amf_size": len(self._last_amf),
                "error": "Open3D not available – stub files returned",
            }

        try:
            pts = np.array(points, dtype=np.float64)
            colors_list = pc_dict.get("colors", [])
            has_colors = len(colors_list) == len(points)

            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(pts)
            if has_colors:
                pcd.colors = o3d.utility.Vector3dVector(np.array(colors_list, dtype=np.float64))

            # Voxel downsample for performance
            pcd = pcd.voxel_down_sample(voxel_size=2.0)

            # Normal estimation
            pcd.estimate_normals(
                o3d.geometry.KDTreeSearchParamHybrid(radius=10.0, max_nn=30)
            )
            pcd.orient_normals_consistent_tangent_plane(100)

            # Poisson reconstruction
            mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                pcd, depth=8
            )

            # Remove low-density vertices
            densities_arr = np.asarray(densities)
            threshold = np.percentile(densities_arr, 5)
            vertices_to_remove = densities_arr < threshold
            mesh.remove_vertices_by_mask(vertices_to_remove)
            mesh.compute_vertex_normals()

            # Export STL
            stl_path = "/tmp/horalscanner_model.stl"
            o3d.io.write_triangle_mesh(stl_path, mesh, write_ascii=True)
            with open(stl_path, "rb") as f:
                self._last_stl = f.read()

            # Export AMF (as XML wrapping STL geometry)
            self._last_amf = self._stl_to_amf(mesh)

            return {
                "ok": True,
                "stl_size": len(self._last_stl),
                "amf_size": len(self._last_amf),
                "error": "",
            }

        except Exception as exc:
            logger.exception("Reconstruction failed")
            return {"ok": False, "stl_size": 0, "amf_size": 0, "error": str(exc)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_model(self, fmt: str = "stl") -> Optional[bytes]:
        if fmt == "stl":
            return self._last_stl
        if fmt == "amf":
            return self._last_amf
        return None

    @staticmethod
    def _stl_to_amf(mesh) -> bytes:
        """Very simple AMF wrapper around triangle mesh geometry."""
        vertices = np.asarray(mesh.vertices)
        triangles = np.asarray(mesh.triangles)

        lines = ['<?xml version="1.0" encoding="utf-8"?>',
                 '<amf unit="millimeter" version="1.1">',
                 ' <object id="1">',
                 '  <mesh>',
                 '   <vertices>']
        for v in vertices:
            lines.append(f'    <vertex><coordinates>'
                         f'<x>{v[0]:.6f}</x><y>{v[1]:.6f}</y><z>{v[2]:.6f}</z>'
                         f'</coordinates></vertex>')
        lines.append('   </vertices>')
        lines.append('   <volume>')
        for t in triangles:
            lines.append(f'    <triangle>'
                         f'<v1>{t[0]}</v1><v2>{t[1]}</v2><v3>{t[2]}</v3>'
                         f'</triangle>')
        lines.append('   </volume>')
        lines.append('  </mesh>')
        lines.append(' </object>')
        lines.append('</amf>')
        return "\n".join(lines).encode("utf-8")
