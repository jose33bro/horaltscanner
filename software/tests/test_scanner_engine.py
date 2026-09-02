import time
import unittest
from unittest import mock

from software.api.scanner_engine import (
    ReconstructionEngine,
    ScanData,
    ScanSession,
)


class ScannerEngineFallbackTests(unittest.TestCase):
    def test_grid_points_are_triangulated_into_ascii_stl(self):
        points = [
            [0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 3.0, 0.0],
            [0.0, 4.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [1.0, 2.0, 0.0],
            [1.0, 3.0, 0.0],
            [1.0, 4.0, 0.0],
        ]

        stl = ReconstructionEngine._points_to_ascii_stl(points)

        self.assertTrue(stl.startswith(b"solid horalscanner"))
        self.assertEqual(stl.count(b"facet normal"), 8)
        self.assertEqual(stl.count(b"vertex"), 24)


class ScanDataBoundedMemoryTests(unittest.TestCase):
    def test_points_are_bounded_and_drop_oldest_first(self):
        data = ScanData(max_points=5)

        for i in range(10):
            data.add_point(float(i), 0.0, 0.0)

        # Only the last `max_points` entries are retained (FIFO eviction).
        self.assertEqual(data.point_count(), 5)
        self.assertEqual([p[0] for p in data.points], [5.0, 6.0, 7.0, 8.0, 9.0])

    def test_colors_stay_in_sync_with_points_when_bounded(self):
        data = ScanData(max_points=3)

        for i in range(6):
            data.add_point(float(i), 0.0, 0.0, r=float(i), g=0.0, b=0.0)

        self.assertEqual(len(data.points), 3)
        self.assertEqual(len(data.colors), 3)
        self.assertEqual([c[0] for c in data.colors], [3.0, 4.0, 5.0])

    def test_unbounded_growth_never_exceeds_default_max_points(self):
        # Regression guard for the unbounded-list memory leak: the default
        # ScanData must never grow past MAX_POINTS even for very long scans.
        from software.api import scanner_engine as se

        data = ScanData()
        for i in range(se.MAX_POINTS + 50):
            data.add_point(float(i), 0.0, 0.0)

        self.assertEqual(data.point_count(), se.MAX_POINTS)


class _FakeVector3dVector(list):
    pass


class _FakePointCloud:
    def __init__(self):
        self.points = []
        self.colors = []

    def voxel_down_sample(self, voxel_size):
        return self

    def estimate_normals(self, *_args, **_kwargs):
        return None

    def orient_normals_consistent_tangent_plane(self, *_args, **_kwargs):
        return None


class _FakeMesh:
    def __init__(self):
        self.vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        self.triangles = [[0, 1, 2]]

    def remove_vertices_by_mask(self, _mask):
        return None

    def compute_vertex_normals(self):
        return None


class _FakeUtility:
    Vector3dVector = staticmethod(lambda arr: _FakeVector3dVector(arr))


class _FakeTriangleMesh:
    @staticmethod
    def create_from_point_cloud_poisson(_pcd, depth):
        return _FakeMesh(), [1.0, 1.0, 1.0]


class _FakeGeometry:
    PointCloud = staticmethod(lambda: _FakePointCloud())
    TriangleMesh = _FakeTriangleMesh
    KDTreeSearchParamHybrid = staticmethod(lambda **kwargs: None)


class _FakeO3D:
    utility = _FakeUtility()
    geometry = _FakeGeometry()


class AsyncReconstructionTests(unittest.TestCase):
    def _make_session_with_points(self, count=150):
        session = ScanSession(simulation=True)
        for i in range(count):
            session._data.add_point(float(i), 0.0, 0.0)
        return session

    def test_reconstruct_returns_immediately_and_reports_progress(self):
        session = self._make_session_with_points()
        engine = ReconstructionEngine(session)

        with (
            mock.patch("software.api.scanner_engine._O3D_AVAILABLE", True),
            mock.patch("software.api.scanner_engine.o3d", _FakeO3D(), create=True),
        ):
            result = engine.reconstruct()

            # The call must return promptly without waiting for the
            # (potentially slow) Poisson pipeline to finish.
            self.assertTrue(result["ok"])
            self.assertTrue(result["in_progress"])

            # Poll status() until the background thread finishes.
            deadline = time.time() + 5
            status = engine.status()
            while status["in_progress"] and time.time() < deadline:
                time.sleep(0.01)
                status = engine.status()

        self.assertFalse(status["in_progress"])
        self.assertTrue(status["result"]["ok"])
        self.assertGreater(status["result"]["stl_size"], 0)

    def test_reconstruct_with_wait_returns_final_result_inline(self):
        session = self._make_session_with_points()
        engine = ReconstructionEngine(session)

        with (
            mock.patch("software.api.scanner_engine._O3D_AVAILABLE", True),
            mock.patch("software.api.scanner_engine.o3d", _FakeO3D(), create=True),
        ):
            result = engine.reconstruct(wait=True)

        self.assertTrue(result["ok"])
        self.assertFalse(result["in_progress"])
        self.assertGreater(result["stl_size"], 0)

    def test_reconstruct_rejects_concurrent_calls_while_in_progress(self):
        session = self._make_session_with_points()
        engine = ReconstructionEngine(session)

        with (
            mock.patch("software.api.scanner_engine._O3D_AVAILABLE", True),
            mock.patch("software.api.scanner_engine.o3d", _FakeO3D(), create=True),
        ):
            first = engine.reconstruct()
            second = engine.reconstruct()
            # Drain the background thread before finishing the test.
            deadline = time.time() + 5
            while engine.status()["in_progress"] and time.time() < deadline:
                time.sleep(0.01)

        self.assertTrue(first["in_progress"])
        self.assertTrue(second["in_progress"])
        self.assertFalse(second.get("started", True))


if __name__ == "__main__":
    unittest.main()
