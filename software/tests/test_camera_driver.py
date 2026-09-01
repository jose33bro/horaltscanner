import unittest
from unittest import mock

import numpy as np

from software.api import camera_driver


class FakeVideoCapture:
    """Minimal cv2.VideoCapture stand-in for LogitechCamera fallback tests."""

    def __init__(self, working_indices, opened_log):
        self._working_indices = working_indices
        self._opened_log = opened_log

    def __call__(self, idx):
        self._opened_log.append(idx)
        return _FakeCap(idx, idx in self._working_indices)


class _FakeCap:
    def __init__(self, idx, works):
        self.idx = idx
        self._works = works
        self.released = False

    def isOpened(self):
        return self._works

    def read(self):
        if not self._works:
            return False, None
        return True, np.zeros((480, 640, 3), dtype=np.uint8)

    def set(self, *_args):
        return True

    def release(self):
        self.released = True


class FakeCv2ForLogitech:
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4

    def __init__(self, working_indices):
        self._opened_log: list = []
        self.VideoCapture = FakeVideoCapture(working_indices, self._opened_log)


class LogitechCameraOpenTests(unittest.TestCase):
    def test_opens_on_configured_device_id_without_fallback(self):
        fake_cv2 = FakeCv2ForLogitech(working_indices={0})
        camera = camera_driver.LogitechCamera(device_id=0)

        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            self.assertTrue(camera.open())

        self.assertEqual(camera.device_id, 0)
        self.assertEqual(fake_cv2._opened_log, [0])

    def test_falls_back_to_working_index_when_configured_one_fails(self):
        # Configured device_id=2 is bad; only index 0 actually works.
        fake_cv2 = FakeCv2ForLogitech(working_indices={0})
        camera = camera_driver.LogitechCamera(device_id=2)

        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            self.assertTrue(camera.open())

        self.assertEqual(camera.device_id, 0)
        # Configured id (2) is tried first, then fallback candidates 0,1,2,3
        # without duplicating the already-tried index 2.
        self.assertEqual(fake_cv2._opened_log, [2, 0])
        self.assertTrue(camera.is_open)

    def test_does_not_duplicate_candidate_indices(self):
        fake_cv2 = FakeCv2ForLogitech(working_indices={3})
        camera = camera_driver.LogitechCamera(device_id=3)

        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            self.assertTrue(camera.open())

        # device_id (3) is also the last fallback candidate; it must only be
        # attempted once.
        self.assertEqual(fake_cv2._opened_log, [3])

    def test_returns_false_and_releases_all_when_nothing_works(self):
        fake_cv2 = FakeCv2ForLogitech(working_indices=set())
        camera = camera_driver.LogitechCamera(device_id=5)

        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            self.assertFalse(camera.open())

        self.assertFalse(camera.is_open)
        self.assertEqual(fake_cv2._opened_log, [5, 0, 1, 2, 3])

    def test_open_returns_false_when_cv2_unavailable(self):
        camera = camera_driver.LogitechCamera(device_id=0)
        with mock.patch.object(camera_driver, "_CV2_AVAILABLE", False):
            self.assertFalse(camera.open())


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


class FakeCv2ForLaser:
    """Minimal cv2 fake for analyze_laser_line tests."""

    IMREAD_COLOR = 1
    THRESH_BINARY = 0

    def __init__(self, lines=None):
        # lines: list of [[x1,y1,x2,y2]] arrays as HoughLinesP would return
        self._lines = lines
        self.threshold_value = None

    def imdecode(self, _data, _mode):
        # Return a 480x640 BGR image with zeros (no signal)
        return np.zeros((480, 640, 3), dtype=np.uint8)

    def threshold(self, channel, thresh, maxval, flags):
        self.threshold_value = thresh
        binary = (channel > thresh).astype(np.uint8) * maxval
        return thresh, binary

    def HoughLinesP(self, _binary, rho, theta, threshold, minLineLength, maxLineGap):
        return self._lines

    # pylint: disable=invalid-name
    def imencode(self, *_args):
        return True, np.array([0], dtype=np.uint8)


class AnalyzeLaserLineTests(unittest.TestCase):
    def _run(self, lines):
        fake_cv2 = FakeCv2ForLaser(lines=lines)
        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            return camera_driver.analyze_laser_line(b"jpeg")

    def test_no_lines_returns_not_detected(self):
        result = self._run(lines=None)
        self.assertTrue(result["analysis_available"])
        self.assertFalse(result["line_detected"])
        self.assertIn("non", result["instruction"].lower())

    def test_vertical_line_returns_zero_angle(self):
        # A perfectly vertical segment: same x, different y
        lines = [np.array([[320, 0, 320, 480]])]
        result = self._run(lines=lines)
        self.assertTrue(result["line_detected"])
        self.assertEqual(result["angle_deg"], 0.0)
        self.assertEqual(result["correction_deg"], 0.0)
        self.assertIn("correct", result["instruction"].lower())

    def test_tilted_right_line_returns_positive_angle_and_left_correction(self):
        # A line tilted clockwise: top at x=300, bottom at x=340 (dx=+40, dy=480)
        # angle ≈ atan2(40, 480) ≈ 4.8°
        lines = [np.array([[300, 0, 340, 480]])]
        result = self._run(lines=lines)
        self.assertTrue(result["line_detected"])
        self.assertGreater(result["angle_deg"], 0)
        self.assertLess(result["correction_deg"], 0)
        self.assertIn("gauche", result["instruction"].lower())

    def test_tilted_left_line_returns_negative_angle_and_right_correction(self):
        # A line tilted counter-clockwise: top at x=340, bottom at x=300
        lines = [np.array([[340, 0, 300, 480]])]
        result = self._run(lines=lines)
        self.assertTrue(result["line_detected"])
        self.assertLess(result["angle_deg"], 0)
        self.assertGreater(result["correction_deg"], 0)
        self.assertIn("droite", result["instruction"].lower())

    def test_cv2_unavailable_returns_not_available(self):
        with mock.patch.object(camera_driver, "_CV2_AVAILABLE", False):
            result = camera_driver.analyze_laser_line(b"jpeg")
        self.assertFalse(result["analysis_available"])
        self.assertFalse(result["line_detected"])


if __name__ == "__main__":
    unittest.main()
