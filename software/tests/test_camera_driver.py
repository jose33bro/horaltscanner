import io
import threading
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
    def setUp(self):
        # Ensure the class-level "last working device" cache doesn't leak
        # state between tests (or from a previous test module run).
        camera_driver.LogitechCamera._last_working_device_id = None

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

    def test_auto_mode_probes_known_indices_until_one_works(self):
        fake_cv2 = FakeCv2ForLogitech(working_indices={1})
        camera = camera_driver.LogitechCamera(device_id="auto")

        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            self.assertTrue(camera.open())

        self.assertEqual(camera.device_id, 1)
        self.assertEqual(fake_cv2._opened_log, [0, 1])

    def test_auto_mode_prefers_stable_logitech_v4l_identity(self):
        stable_path = "/dev/v4l/by-id/usb-046d_HD_Webcam_C270-video-index0"
        fake_cv2 = FakeCv2ForLogitech(working_indices={stable_path})
        camera = camera_driver.LogitechCamera(device_id="auto")

        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
            mock.patch.object(
                camera_driver.glob,
                "glob",
                side_effect=lambda pattern: [stable_path] if "by-id" in pattern else [],
            ),
        ):
            self.assertTrue(camera.open())

        self.assertEqual(camera.device_id, stable_path)
        self.assertEqual(fake_cv2._opened_log, [stable_path])

    def test_auto_mode_discovers_video_indices_above_fixed_fallbacks(self):
        fake_cv2 = FakeCv2ForLogitech(working_indices={7})
        camera = camera_driver.LogitechCamera(device_id="auto")

        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
            mock.patch.object(
                camera_driver.glob,
                "glob",
                side_effect=lambda pattern: ["/dev/video7"]
                if pattern == "/dev/video[0-9]*"
                else [],
            ),
        ):
            self.assertTrue(camera.open())

        self.assertEqual(camera.device_id, 7)
        self.assertEqual(fake_cv2._opened_log, [7])

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

    def test_caches_last_working_device_and_tries_it_first(self):
        # First camera finds device 3 working; this should be cached at the
        # class level.
        fake_cv2 = FakeCv2ForLogitech(working_indices={3})
        camera = camera_driver.LogitechCamera(device_id=3)
        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            self.assertTrue(camera.open())
        self.assertEqual(camera_driver.LogitechCamera._last_working_device_id, 3)

        # A second camera configured with a different (bad) device_id should
        # try the cached index 3 before falling back to its own candidates,
        # avoiding a full re-probe of every device.
        fake_cv2_2 = FakeCv2ForLogitech(working_indices={3})
        camera2 = camera_driver.LogitechCamera(device_id=9)
        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2_2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            self.assertTrue(camera2.open())
        self.assertEqual(camera2.device_id, 3)
        self.assertEqual(fake_cv2_2._opened_log[0], 3)


class FakePicamera2:
    """Minimal Picamera2 stand-in returning a known BGR-ordered array."""

    def __init__(self, array):
        self._array = array
        self.started = False
        self.stopped = False
        self.closed = False

    def create_still_configuration(self, **_kwargs):
        return {}

    def configure(self, _config):
        return None

    def start(self):
        self.started = True

    def capture_array(self):
        return self._array

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class PiCameraCaptureTests(unittest.TestCase):
    def test_capture_jpeg_corrects_picamera2_bgr_ordering(self):
        # picamera2's "RGB888" configuration actually yields BGR-ordered
        # pixels (libcamera/DRM naming quirk). Build a frame that is pure
        # blue in that raw ordering and assert the saved JPEG is red,
        # proving the channel swap fix is applied before encoding.
        raw_bgr_frame = np.zeros((4, 4, 3), dtype=np.uint8)
        raw_bgr_frame[:, :, 2] = 255  # true "red" value, stored at the
        # last position because picamera2 delivers it in BGR memory order

        fake_cam = FakePicamera2(raw_bgr_frame)
        camera = camera_driver.PiCamera()
        with mock.patch.object(camera_driver, "_PICAM_AVAILABLE", True), \
                mock.patch.object(camera_driver, "Picamera2", lambda: fake_cam, create=True):
            self.assertTrue(camera.open())

        jpeg = camera.capture_jpeg()
        self.assertIsNotNone(jpeg)

        from PIL import Image
        decoded = np.array(Image.open(io.BytesIO(jpeg)).convert("RGB"))
        # A pixel that was "blue" in the raw BGR-ordered array must be
        # reported as red once corrected to true RGB order.
        self.assertGreater(int(decoded[0, 0, 0]), 200)
        self.assertLess(int(decoded[0, 0, 2]), 50)

    def test_capture_rejects_overlap_while_picamera_is_busy(self):
        started = threading.Event()
        release = threading.Event()

        class BlockingPicamera:
            def capture_array(self):
                started.set()
                release.wait(1)
                return np.zeros((4, 4, 3), dtype=np.uint8)

        camera = camera_driver.PiCamera()
        camera._cam = BlockingPicamera()
        camera.LOCK_WAIT_SECONDS = 0.01
        capture_thread = threading.Thread(target=camera.capture_jpeg)
        capture_thread.start()
        self.assertTrue(started.wait(0.5))

        self.assertIsNone(camera.capture_jpeg())
        self.assertIn("occupee", camera.last_error)

        release.set()
        capture_thread.join(1)
        self.assertFalse(capture_thread.is_alive())


class FakeCv2:
    IMREAD_COLOR = 1
    COLOR_BGR2GRAY = 2
    CV_64F = 3
    INTER_AREA = 4

    def __init__(self, detected_size=None):
        self.detected_size = detected_size
        self.checked_sizes = []
        self.resize_calls = []

    def imdecode(self, _data, _mode):
        return np.zeros((960, 1280, 3), dtype=np.uint8)

    def resize(self, _image, size, interpolation):
        self.resize_calls.append((size, interpolation))
        return np.zeros((size[1], size[0], 3), dtype=np.uint8)

    def cvtColor(self, image, _mode):
        return np.full(image.shape[:2], 50, dtype=np.uint8)

    def findChessboardCorners(self, _gray, size):
        self.checked_sizes.append(size)
        if size != self.detected_size:
            return False, None
        corners = np.tile(np.array([[[525.0, 375.0]]], dtype=np.float32), (size[0] * size[1], 1, 1))
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
        self.assertEqual(result["analysis_width"], 960)
        self.assertEqual(result["analysis_height"], 720)
        self.assertEqual(fake_cv2.resize_calls, [((960, 720), fake_cv2.INTER_AREA)])
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
