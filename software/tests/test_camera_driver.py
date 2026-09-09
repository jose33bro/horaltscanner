import io
import threading
import time
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
        self.events = []

    def isOpened(self):
        return self._works

    def read(self):
        self.events.append(("read",))
        if not self._works:
            return False, None
        return True, np.zeros((480, 640, 3), dtype=np.uint8)

    def set(self, *args):
        self.events.append(("set", *args))
        return True

    def release(self):
        self.released = True


class FakeCv2ForLogitech:
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_BUFFERSIZE = 38

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
        self.assertEqual(
            camera._cap.events,
            [
                ("set", fake_cv2.CAP_PROP_FRAME_WIDTH, 1920),
                ("set", fake_cv2.CAP_PROP_FRAME_HEIGHT, 1080),
                ("set", fake_cv2.CAP_PROP_BUFFERSIZE, 1),
                ("read",),
            ],
        )

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


class _QueuedCapture:
    def __init__(self, frames, *, fail_read=False):
        self.frames = list(frames)
        self.fail_read = fail_read
        self.grab_calls = 0
        self.read_calls = 0

    def isOpened(self):
        return True

    def grab(self):
        self.grab_calls += 1
        if not self.frames:
            return False
        self.frames.pop(0)
        return True

    def read(self):
        self.read_calls += 1
        if self.fail_read or not self.frames:
            return False, None
        return True, self.frames.pop(0)


class LogitechCameraFreshFrameTests(unittest.TestCase):
    def setUp(self):
        self.camera = camera_driver.LogitechCamera(device_id=0)

    def test_discards_stale_frames_and_encodes_latest_bounded_frame(self):
        stale_one = np.full((2, 2, 3), 1, dtype=np.uint8)
        stale_two = np.full((2, 2, 3), 2, dtype=np.uint8)
        latest = np.full((2, 2, 3), 3, dtype=np.uint8)
        capture = _QueuedCapture([stale_one, stale_two, latest])
        self.camera._cap = capture
        encoded = np.array([7, 8, 9], dtype=np.uint8)
        fake_cv2 = mock.Mock()
        fake_cv2.imencode.return_value = (True, encoded)

        with mock.patch.object(camera_driver, "cv2", fake_cv2, create=True):
            result = self.camera.capture_jpeg()

        self.assertEqual(result, encoded.tobytes())
        self.assertEqual(capture.grab_calls, self.camera.FRESH_FRAME_GRABS)
        self.assertEqual(capture.read_calls, 1)
        np.testing.assert_array_equal(fake_cv2.imencode.call_args.args[1], latest)

    def test_fresh_frame_read_failure_returns_none_without_encoding(self):
        capture = _QueuedCapture(
            [
                np.zeros((2, 2, 3), dtype=np.uint8),
                np.ones((2, 2, 3), dtype=np.uint8),
            ],
            fail_read=True,
        )
        self.camera._cap = capture
        fake_cv2 = mock.Mock()

        with mock.patch.object(camera_driver, "cv2", fake_cv2, create=True):
            result = self.camera.capture_jpeg()

        self.assertIsNone(result)
        self.assertEqual(capture.grab_calls, self.camera.FRESH_FRAME_GRABS)
        self.assertEqual(capture.read_calls, 1)
        fake_cv2.imencode.assert_not_called()
        self.assertIn("fresh frame", self.camera.last_error)

    def test_queue_discard_loop_is_strictly_bounded(self):
        class EndlessCapture(_QueuedCapture):
            def grab(self):
                self.grab_calls += 1
                return True

        latest = np.full((2, 2, 3), 4, dtype=np.uint8)
        capture = EndlessCapture([latest])
        self.camera._cap = capture
        fake_cv2 = mock.Mock()
        fake_cv2.imencode.return_value = (True, np.array([4], dtype=np.uint8))

        with mock.patch.object(camera_driver, "cv2", fake_cv2, create=True):
            self.assertEqual(self.camera.capture_jpeg(), b"\x04")

        self.assertEqual(capture.grab_calls, self.camera.FRESH_FRAME_GRABS)
        self.assertEqual(capture.read_calls, 1)


class FakePicamera2:
    """Minimal Picamera2 stand-in returning a known BGR-ordered array."""

    def __init__(self, array):
        self._array = array
        self.started = False
        self.stopped = False
        self.closed = False
        self.camera_controls = {
            name: (None, None, None)
            for name in camera_driver.PiCamera.PHOTOMETRIC_CONTROL_NAMES
        }
        self.current_controls = {
            "AeEnable": True,
            "AwbEnable": True,
            "ExposureTime": 12000,
            "AnalogueGain": 2.5,
            "ColourGains": (1.4, 1.8),
        }
        self.control_calls = []
        self.capture_controls = []
        self._pending_controls = {}
        self._pending_delay = 0
        self.manual_control_delay_frames = 0

    def create_still_configuration(self, **_kwargs):
        return {}

    def configure(self, _config):
        return None

    def start(self):
        self.started = True

    def _apply_pending_controls(self):
        if self._pending_delay > 0:
            self._pending_delay -= 1
            return
        self.current_controls.update(self._pending_controls)
        self._pending_controls = {}

    def capture_arrays(self, _names):
        self._apply_pending_controls()
        self.capture_controls.append(dict(self.current_controls))
        return [self._array], dict(self.current_controls)

    def capture_metadata(self):
        self._apply_pending_controls()
        return dict(self.current_controls)

    def set_controls(self, controls):
        self.control_calls.append(dict(controls))
        self._pending_controls.update(controls)
        if controls.get("AeEnable") is False:
            self._pending_delay = self.manual_control_delay_frames

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
            def capture_arrays(self, _names):
                started.set()
                release.wait(1)
                return (
                    [np.zeros((4, 4, 3), dtype=np.uint8)],
                    {},
                )

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


class PiCameraPhotometricControlTests(unittest.TestCase):
    def setUp(self):
        self.raw_frame = np.zeros((4, 4, 3), dtype=np.uint8)
        self.fake_cam = FakePicamera2(self.raw_frame)
        self.camera = camera_driver.PiCamera()
        self.camera._cam = self.fake_cam

    def test_matched_context_uses_identical_controls_and_restores_auto(self):
        with self.camera.matched_photometric_controls() as session:
            controls = session.lock_from_metadata(session.capture_metadata())
            session.confirm_locked_controls()
            self.assertIsNotNone(session.capture_jpeg()[0])
            self.assertIsNotNone(session.capture_jpeg()[0])

        self.assertEqual(
            controls,
            {
                "ExposureTime": 12000,
                "AnalogueGain": 2.5,
                "ColourGains": [1.4, 1.8],
            },
        )
        self.assertEqual(len(self.fake_cam.capture_controls), 2)
        self.assertEqual(
            self.fake_cam.capture_controls[0],
            self.fake_cam.capture_controls[1],
        )
        self.assertFalse(self.fake_cam.capture_controls[0]["AeEnable"])
        self.assertFalse(self.fake_cam.capture_controls[0]["AwbEnable"])
        self.assertEqual(
            self.fake_cam.control_calls[-1],
            {"AeEnable": True, "AwbEnable": True},
        )
        self.fake_cam.capture_metadata()
        self.assertTrue(self.fake_cam.current_controls["AeEnable"])
        self.assertTrue(self.fake_cam.current_controls["AwbEnable"])

    def test_matched_context_restores_controls_after_capture_error(self):
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            with self.camera.matched_photometric_controls():
                raise RuntimeError("capture failed")

        self.fake_cam.capture_metadata()
        self.assertTrue(self.fake_cam.current_controls["AeEnable"])
        self.assertTrue(self.fake_cam.current_controls["AwbEnable"])

    def test_matched_context_restores_controls_when_body_is_cancelled(self):
        class Cancelled(RuntimeError):
            pass

        with self.assertRaisesRegex(Cancelled, "cancelled"):
            with self.camera.matched_photometric_controls():
                raise Cancelled("cancelled")

        self.fake_cam.capture_metadata()
        self.assertTrue(self.fake_cam.current_controls["AeEnable"])
        self.assertTrue(self.fake_cam.current_controls["AwbEnable"])

    def test_matched_context_restores_prior_manual_controls(self):
        self.fake_cam.current_controls.update({
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": 7000,
            "AnalogueGain": 1.75,
            "ColourGains": (1.1, 1.3),
        })
        self.camera.set_photometric_controls(
            dict(self.fake_cam.current_controls)
        )
        self.fake_cam.capture_metadata()

        with self.camera.matched_photometric_controls():
            pass

        self.assertEqual(
            self.fake_cam.control_calls[-1],
            {
                "AeEnable": False,
                "AwbEnable": False,
                "ExposureTime": 7000,
                "AnalogueGain": 1.75,
                "ColourGains": (1.1, 1.3),
            },
        )

    def test_external_capture_is_rejected_during_matched_session(self):
        with self.camera.matched_photometric_controls() as session:
            session.lock_from_metadata(session.capture_metadata())
            self.assertIsNone(self.camera.capture_jpeg())
            self.assertIn("reserved", self.camera.last_error)

    def test_competing_context_does_not_clear_active_session_token(self):
        with self.camera.matched_photometric_controls() as winning_session:
            winning_token = self.camera._active_session_token
            with self.assertRaisesRegex(
                camera_driver.PhotometricControlError,
                "already has an active",
            ):
                with self.camera.matched_photometric_controls():
                    self.fail("competing context must not yield")
            self.assertIs(self.camera._active_session_token, winning_token)
            winning_session.lock_from_metadata(
                winning_session.capture_metadata()
            )
            self.assertIsNotNone(winning_session.capture_jpeg()[0])

    def test_confirmation_discards_stale_post_lock_requests(self):
        self.fake_cam.manual_control_delay_frames = 2
        with self.camera.matched_photometric_controls() as session:
            session.lock_from_metadata(session.capture_metadata())
            confirmed = session.confirm_locked_controls()
            _jpeg, ambient_metadata = session.capture_jpeg()

        self.assertEqual(confirmed["ExposureTime"], 12000)
        self.assertFalse(ambient_metadata["AeEnable"])
        self.assertFalse(ambient_metadata["AwbEnable"])

    def test_absent_awb_enable_metadata_accepts_stable_numeric_controls(self):
        original_metadata = self.fake_cam.capture_metadata
        original_capture = self.fake_cam.capture_arrays

        def metadata_without_awb():
            metadata = original_metadata()
            metadata.pop("AwbEnable", None)
            return metadata

        def capture_without_awb(names):
            arrays, metadata = original_capture(names)
            metadata.pop("AwbEnable", None)
            return arrays, metadata

        self.fake_cam.capture_metadata = metadata_without_awb
        self.fake_cam.capture_arrays = capture_without_awb

        with self.camera.matched_photometric_controls() as session:
            session.lock_from_metadata(session.capture_metadata())
            confirmed = session.confirm_locked_controls()
            _jpeg, frame_metadata = session.capture_jpeg()

        self.assertNotIn("AwbEnable", confirmed)
        self.assertNotIn("AwbEnable", frame_metadata)
        self.assertEqual(frame_metadata["ExposureTime"], 12000)
        self.assertEqual(frame_metadata["AnalogueGain"], 2.5)
        self.assertEqual(frame_metadata["ColourGains"], (1.4, 1.8))

    def test_missing_colour_gains_metadata_is_rejected_with_diagnostics(self):
        original_capture = self.fake_cam.capture_arrays

        with self.camera.matched_photometric_controls() as session:
            session.lock_from_metadata(session.capture_metadata())
            session.confirm_locked_controls()

            def capture_without_colour_gains(names):
                arrays, metadata = original_capture(names)
                metadata.pop("ColourGains")
                return arrays, metadata

            self.fake_cam.capture_arrays = capture_without_colour_gains
            with self.assertRaisesRegex(
                camera_driver.PhotometricControlError,
                "missing ColourGains.*available relevant metadata: "
                "AwbEnable=False, ExposureTime=12000, AnalogueGain=2.5",
            ):
                session.capture_jpeg()

    def test_drifting_colour_gains_metadata_is_rejected(self):
        original_capture = self.fake_cam.capture_arrays

        with self.camera.matched_photometric_controls() as session:
            session.lock_from_metadata(session.capture_metadata())
            session.confirm_locked_controls()

            def capture_with_colour_drift(names):
                arrays, metadata = original_capture(names)
                metadata["ColourGains"] = (2.4, 3.1)
                return arrays, metadata

            self.fake_cam.capture_arrays = capture_with_colour_drift
            with self.assertRaisesRegex(
                camera_driver.PhotometricControlError,
                r"ColourGains=.*differs from locked.*available relevant metadata",
            ):
                session.capture_jpeg()

    def test_exposure_and_gain_drift_are_rejected(self):
        for name, value in (("ExposureTime", 24000), ("AnalogueGain", 7.5)):
            with self.subTest(name=name):
                fake_cam = FakePicamera2(self.raw_frame)
                camera = camera_driver.PiCamera()
                camera._cam = fake_cam
                original_capture = fake_cam.capture_arrays
                with camera.matched_photometric_controls() as session:
                    session.lock_from_metadata(session.capture_metadata())
                    session.confirm_locked_controls()

                    def capture_with_drift(names, *, field=name, drift=value):
                        arrays, metadata = original_capture(names)
                        metadata[field] = drift
                        return arrays, metadata

                    fake_cam.capture_arrays = capture_with_drift
                    with self.assertRaisesRegex(
                        camera_driver.PhotometricControlError,
                        rf"{name}=.*differs from locked.*available relevant metadata",
                    ):
                        session.capture_jpeg()

    def test_invalid_photometric_metadata_is_rejected(self):
        locked = {
            "ExposureTime": 12000,
            "AnalogueGain": 2.5,
            "ColourGains": (1.4, 1.8),
        }
        valid = {
            "ExposureTime": 12000,
            "AnalogueGain": 2.5,
            "ColourGains": (1.4, 1.8),
        }
        cases = (
            ("AwbEnable", True, "AwbEnable=True"),
            ("AwbEnable", 0, "invalid non-boolean"),
            ("ExposureTime", "bad", "invalid photometric metadata"),
            ("AnalogueGain", float("inf"), "differs from locked"),
            ("ColourGains", (1.4,), "exactly red and blue"),
            ("ColourGains", (1.4, float("nan")), "differs from locked"),
        )
        for name, value, expected in cases:
            with self.subTest(name=name, value=value):
                metadata = dict(valid)
                metadata[name] = value
                mismatch = self.camera._photometric_metadata_mismatch(
                    metadata, locked
                )
                self.assertIn(expected, mismatch)
                self.assertIn("available relevant metadata:", mismatch)

    def test_frame_metadata_mismatch_fails_and_restores_controls(self):
        original_capture = self.fake_cam.capture_arrays

        def mismatched_capture(names):
            arrays, metadata = original_capture(names)
            metadata["AnalogueGain"] = 9.0
            return arrays, metadata

        self.fake_cam.capture_arrays = mismatched_capture
        with self.assertRaisesRegex(
            camera_driver.PhotometricControlError,
            "does not match",
        ):
            with self.camera.matched_photometric_controls() as session:
                session.lock_from_metadata(session.capture_metadata())
                session.capture_jpeg()

        self.assertEqual(
            self.fake_cam.control_calls[-1],
            {"AeEnable": True, "AwbEnable": True},
        )

    def test_restore_failure_is_explicit_after_success(self):
        original_set = self.fake_cam.set_controls

        def fail_second_auto_restore(controls):
            if (
                controls == {"AeEnable": True, "AwbEnable": True}
                and any(
                    call.get("AeEnable") is False
                    for call in self.fake_cam.control_calls
                )
            ):
                raise RuntimeError("restore failed")
            original_set(controls)

        self.fake_cam.set_controls = fail_second_auto_restore
        with self.assertRaisesRegex(
            camera_driver.PhotometricControlError,
            "failed to restore",
        ):
            with self.camera.matched_photometric_controls() as session:
                session.lock_from_metadata(session.capture_metadata())

        self.assertIsNotNone(self.camera._active_session_token)

    def test_restore_failure_preserves_cancellation_exception(self):
        class Cancelled(RuntimeError):
            pass

        original_set = self.fake_cam.set_controls

        def fail_restore(controls):
            if len(self.fake_cam.control_calls) >= 1:
                raise RuntimeError("restore failed")
            original_set(controls)

        self.fake_cam.set_controls = fail_restore
        with self.assertRaisesRegex(Cancelled, "cancelled"):
            with self.camera.matched_photometric_controls():
                raise Cancelled("cancelled")

    def test_blocked_capture_queues_restore_and_releases_quarantine_later(self):
        entered = threading.Event()
        release = threading.Event()
        original_capture = self.fake_cam.capture_arrays
        capture_errors = []
        capture_thread = None

        with self.assertRaisesRegex(
            camera_driver.PhotometricControlError,
            "controls were restored.*quarantine",
        ):
            with self.camera.matched_photometric_controls() as session:
                session.lock_from_metadata(session.capture_metadata())
                session.confirm_locked_controls()

                def blocked_capture(names):
                    entered.set()
                    release.wait(1)
                    return original_capture(names)

                self.fake_cam.capture_arrays = blocked_capture

                def capture():
                    try:
                        session.capture_jpeg()
                    except Exception as exc:
                        capture_errors.append(exc)

                capture_thread = threading.Thread(target=capture)
                capture_thread.start()
                self.assertTrue(entered.wait(0.5))

        self.assertEqual(
            self.fake_cam.control_calls[-1],
            {"AeEnable": True, "AwbEnable": True},
        )
        self.assertIsNotNone(self.camera._active_session_token)
        release.set()
        capture_thread.join(1)
        deadline = time.monotonic() + 1
        while (
            self.camera._active_session_token is not None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        self.assertIsNone(self.camera._active_session_token)
        self.assertTrue(capture_errors)

    def test_unsupported_controls_fail_before_camera_state_changes(self):
        del self.fake_cam.camera_controls["ColourGains"]

        with self.assertRaisesRegex(
            camera_driver.PhotometricControlUnsupported,
            "ColourGains",
        ):
            with self.camera.matched_photometric_controls():
                self.fail("unsupported context must not yield")

        self.assertEqual(self.fake_cam.control_calls, [])


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


class FakeCv2SB(FakeCv2):
    def findChessboardCorners(self, _gray, size, _flags=0):
        self.checked_sizes.append(("classic", size))
        return False, None

    def findChessboardCornersSB(self, _gray, size, _flags=0):
        self.checked_sizes.append(("sb", size))
        corners = np.tile(
            np.array([[[480.0, 360.0]]], dtype=np.float32),
            (size[0] * size[1], 1, 1),
        )
        return size == (11, 6), corners


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
        self.assertTrue(result["checkerboard_matches_expected"])
        self.assertEqual(result["center_offset_x_px"], 60.5)
        self.assertEqual(result["center_offset_y_px"], 20.5)
        self.assertEqual(result["analysis_width"], 960)
        self.assertEqual(result["analysis_height"], 720)
        self.assertEqual(fake_cv2.resize_calls, [((960, 720), fake_cv2.INTER_AREA)])
        self.assertEqual(fake_cv2.checked_sizes, [(11, 6)])

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
        self.assertEqual(
            fake_cv2.checked_sizes,
            [(11, 6), (10, 6), (12, 7), (9, 6)],
        )

    def test_diagnostic_labels_secondary_pattern_as_not_calibration_board(self):
        fake_cv2 = FakeCv2(detected_size=(10, 6))
        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            result = camera_driver.analyze_camera_frame(b"jpeg")
        self.assertTrue(result["checkerboard_found"])
        self.assertEqual(result["checkerboard_columns"], 10)
        self.assertFalse(result["checkerboard_matches_expected"])

    def test_diagnostic_uses_sb_when_classic_fails_for_exact_board(self):
        fake_cv2 = FakeCv2SB()
        with (
            mock.patch.object(camera_driver, "cv2", fake_cv2, create=True),
            mock.patch.object(camera_driver, "_CV2_AVAILABLE", True),
        ):
            result = camera_driver.analyze_camera_frame(b"jpeg")
        self.assertTrue(result["checkerboard_found"])
        self.assertEqual(result["checkerboard_detection_method"], "sb")
        self.assertEqual(result["checkerboard_columns"], 11)
        self.assertEqual(
            fake_cv2.checked_sizes,
            [("classic", (11, 6)), ("sb", (11, 6))],
        )


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
