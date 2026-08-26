import unittest
from unittest import mock

import numpy as np

from software.api import camera_driver


class FakeCv2:
    IMREAD_COLOR = 1
    COLOR_BGR2GRAY = 2
    CV_64F = 3

    def __init__(self, detected_size=None):
        self.detected_size = detected_size
        self.checked_sizes = []

    def imdecode(self, _data, _mode):
        return np.zeros((960, 1280, 3), dtype=np.uint8)

    def cvtColor(self, _image, _mode):
        return np.full((960, 1280), 50, dtype=np.uint8)

    def findChessboardCorners(self, _gray, size):
        self.checked_sizes.append(size)
        if size != self.detected_size:
            return False, None
        corners = np.tile(np.array([[[700.0, 500.0]]], dtype=np.float32), (size[0] * size[1], 1, 1))
        return True, corners

    def Laplacian(self, _gray, _depth):
        return np.array([0.0, 2.0])


class AnalyzeCameraFrameTests(unittest.TestCase):
    def test_detects_11_by_6_board_and_reports_center_offset(self):
        fake_cv2 = FakeCv2(detected_size=(11, 6))

        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            result = camera_driver.analyze_camera_frame(b"jpeg")

        self.assertTrue(result["checkerboard_found"])
        self.assertEqual(result["checkerboard_columns"], 11)
        self.assertEqual(result["checkerboard_rows"], 6)
        self.assertEqual(result["center_offset_x_px"], 60.5)
        self.assertEqual(result["center_offset_y_px"], 20.5)
        self.assertEqual(fake_cv2.checked_sizes, [(12, 7), (11, 6)])

    def test_reports_no_center_when_supported_boards_are_absent(self):
        fake_cv2 = FakeCv2()

        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            result = camera_driver.analyze_camera_frame(b"jpeg")

        self.assertFalse(result["checkerboard_found"])
        self.assertIsNone(result["checkerboard_columns"])
        self.assertIsNone(result["center_offset_x_px"])
        self.assertEqual(fake_cv2.checked_sizes, [(12, 7), (11, 6), (9, 6)])


if __name__ == "__main__":
    unittest.main()
