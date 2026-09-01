import unittest

from software.api.scanner_engine import ReconstructionEngine


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


if __name__ == "__main__":
    unittest.main()
