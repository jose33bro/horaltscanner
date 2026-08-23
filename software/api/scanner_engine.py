"""
3D scanning engine – point cloud acquisition, fusion, and mesh reconstruction.
Uses Open3D for Poisson surface reconstruction.
"""

import logging
import os
import struct
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import open3d as o3d  # type: ignore
    OPEN3D_AVAILABLE = True
except ImportError:
    OPEN3D_AVAILABLE = False
    logger.warning("open3d not available – reconstruction disabled")


class PointCloudBuffer:
    """Thread-safe accumulator for 3D points + colours."""

    def __init__(self):
        self._points: List[List[float]] = []
        self._colors: List[List[float]] = []
        self._lock = threading.Lock()

    def add_point(self, x: float, y: float, z: float,
                  r: float = 1.0, g: float = 1.0, b: float = 1.0) -> None:
        with self._lock:
            self._points.append([x, y, z])
            self._colors.append([r, g, b])

    def add_points(self, pts: np.ndarray, colors: Optional[np.ndarray] = None) -> None:
        with self._lock:
            self._points.extend(pts.tolist())
            if colors is not None:
                self._colors.extend(colors.tolist())
            else:
                n = len(pts)
                self._colors.extend([[1.0, 1.0, 1.0]] * n)

    def get_numpy(self):
        with self._lock:
            pts = np.array(self._points, dtype=np.float64) if self._points else np.empty((0, 3))
            clr = np.array(self._colors, dtype=np.float64) if self._colors else np.empty((0, 3))
        return pts, clr

    def count(self) -> int:
        with self._lock:
            return len(self._points)

    def reset(self) -> None:
        with self._lock:
            self._points.clear()
            self._colors.clear()

    def to_dict(self) -> Dict[str, Any]:
        pts, clr = self.get_numpy()
        return {
            "points": pts.tolist(),
            "colors": clr.tolist(),
            "count": len(pts),
        }


def triangulate_laser_line(
    frame: np.ndarray,
    angle_deg: float,
    laser_plane_angle_deg: float = 30.0,
) -> Optional[np.ndarray]:
    """
    Simple structured-light triangulation.
    Finds brightest row in each column (laser line), converts pixel → 3D.
    Returns Nx3 array of (X, Y, Z) points in mm.
    """
    try:
        import cv2  # type: ignore
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        h, w = gray.shape
        pts: List[List[float]] = []

        # Camera intrinsics (approximate for Logitech C270 @ 720p)
        fx = 700.0
        cx = w / 2.0
        cy = h / 2.0

        laser_rad = np.deg2rad(laser_plane_angle_deg)
        angle_rad = np.deg2rad(angle_deg)

        for col in range(w):
            col_data = gray[:, col]
            peak = int(np.argmax(col_data))
            if col_data[peak] < 60:
                continue
            # Back-project pixel to camera ray
            v = (peak - cy) / fx  # normalised v direction
            # Laser plane: tan(laser_rad) * Z = X_cam
            # For each column: X_cam = (col - cx)/fx * Z
            # Z from intersection with laser plane
            u = (col - cx) / fx
            z = 100.0 / (np.tan(laser_rad) - u + 1e-9)  # rough depth in mm
            x = u * z
            y_rot = z * np.sin(angle_rad)
            z_rot = z * np.cos(angle_rad)
            pts.append([x, y_rot, z_rot])

        return np.array(pts) if pts else None
    except Exception as exc:
        logger.debug("triangulate_laser_line error: %s", exc)
        return None


class ScannerEngine:
    """Manages scan state and 3D reconstruction pipeline."""

    def __init__(self):
        self.buffer = PointCloudBuffer()
        self._scanning = False
        self._start_time: Optional[float] = None
        self._quality: float = 0.0

    def start(self) -> None:
        self.buffer.reset()
        self._scanning = True
        self._start_time = time.time()
        self._quality = 0.0
        logger.info("Scan started")

    def stop(self) -> None:
        self._scanning = False
        logger.info("Scan stopped – %d points", self.buffer.count())

    @property
    def scanning(self) -> bool:
        return self._scanning

    def status(self) -> Dict[str, Any]:
        elapsed = round(time.time() - self._start_time, 1) if self._start_time else 0
        return {
            "scanning": self._scanning,
            "points": self.buffer.count(),
            "elapsed_s": elapsed,
            "quality": round(self._quality, 2),
        }

    def ingest_laser_frame(
        self,
        frame: np.ndarray,
        rotation_deg: float,
        color_frame: Optional[np.ndarray] = None,
    ) -> int:
        """Process one laser-illuminated frame and add points to buffer."""
        pts = triangulate_laser_line(frame, rotation_deg)
        if pts is None or len(pts) == 0:
            return 0
        colors = None
        if color_frame is not None:
            try:
                import cv2  # type: ignore
                h, w = frame.shape[:2]
                clr = cv2.resize(color_frame, (w, h))
                colors = clr.reshape(-1, 3).astype(np.float64) / 255.0
                # Sample only those rows/cols that yielded points
                colors = colors[: len(pts)]
            except Exception:
                pass
        self.buffer.add_points(pts, colors)
        self._quality = min(1.0, self.buffer.count() / 50000.0)
        return len(pts)

    def reconstruct_mesh(self) -> Optional[bytes]:
        """
        Run Poisson surface reconstruction on accumulated point cloud.
        Returns STL bytes or None.
        """
        if not OPEN3D_AVAILABLE:
            logger.warning("open3d unavailable – cannot reconstruct")
            return None
        pts, clr = self.buffer.get_numpy()
        if len(pts) < 100:
            logger.warning("Too few points for reconstruction: %d", len(pts))
            return None
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        if len(clr) == len(pts):
            pcd.colors = o3d.utility.Vector3dVector(clr)
        pcd.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=5.0, max_nn=30)
        )
        pcd.orient_normals_consistent_tangent_plane(100)
        mesh, _ = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
            pcd, depth=9
        )
        mesh = mesh.simplify_quadric_decimation(100000)
        tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
        tmp.close()
        o3d.io.write_triangle_mesh(tmp.name, mesh)
        with open(tmp.name, "rb") as f:
            data = f.read()
        os.unlink(tmp.name)
        return data

    def export_stl(self) -> Optional[bytes]:
        return self.reconstruct_mesh()

    def export_amf(self) -> Optional[bytes]:
        """Export as AMF (XML-based, with colour support)."""
        if not OPEN3D_AVAILABLE:
            return None
        pts, clr = self.buffer.get_numpy()
        if len(pts) < 100:
            return None
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        if len(clr) == len(pts):
            pcd.colors = o3d.utility.Vector3dVector(clr)
        pcd.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=5.0, max_nn=30)
        )
        pcd.orient_normals_consistent_tangent_plane(100)
        mesh, _ = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=9)
        tmp = tempfile.NamedTemporaryFile(suffix=".amf", delete=False)
        tmp.close()
        written = o3d.io.write_triangle_mesh(tmp.name, mesh)
        if not written:
            # fallback: write STL inside AMF wrapper
            stl = self.export_stl() or b""
            os.unlink(tmp.name)
            return _stl_bytes_to_minimal_amf(stl)
        with open(tmp.name, "rb") as f:
            data = f.read()
        os.unlink(tmp.name)
        return data


def _stl_bytes_to_minimal_amf(stl: bytes) -> bytes:
    """Wrap binary STL data inside a minimal AMF file."""
    import base64
    b64 = base64.b64encode(stl).decode()
    amf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<amf unit="millimeter">\n'
        '  <object id="1">\n'
        '    <mesh><stl_data encoding="base64">\n'
        f"{b64}\n"
        "    </stl_data></mesh>\n"
        "  </object>\n"
        "</amf>\n"
    )
    return amf.encode()
