import copy
import json
import math
import shutil
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from software.api.geometric_calibration import (
    AtomicCalibrationStore,
    CalibrationCancelled,
    CalibrationError,
    CheckerboardDetectionRejected,
    CheckerboardDetectionTimeout,
    GeometricCalibrationService,
    BOARD_TO_SCANNER_AT_REFERENCE,
    checkerboard_view_metrics,
    checkerboard_points,
    fit_plane_robust,
    transform_from_beam,
    validate_calibration_payload,
    validate_view_diversity,
)


ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / ".test-geometric-calibration"


def valid_calibration():
    camera = {
        "intrinsic_matrix": [[800, 0, 320], [0, 800, 240], [0, 0, 1]],
        "distortion_coefficients": [0, 0, 0, 0, 0],
        "camera_to_scanner": np.eye(4).tolist(),
        "quality": {
            "accepted": True,
            "rms_px": 0.2,
            "maximum_rms_px": 1.0,
            "extrinsic_translation_rms_mm": 0.3,
            "maximum_extrinsic_rms_mm": 5.0,
            "extrinsic_rotation_rms_deg": 0.2,
            "maximum_extrinsic_rms_deg": 3.0,
        },
    }
    plane = {
        "normal": [1, 0, 0],
        "offset_mm": -20,
        "quality": {"accepted": True, "rms_mm": 0.2, "maximum_rms_mm": 2.0},
    }
    return {
        "checkerboard": {
            "board_columns": 11,
            "board_rows": 6,
            "square_size_mm": 13,
        },
        "cameras": {"pi": copy.deepcopy(camera), "usb": copy.deepcopy(camera)},
        "laser_planes": {"left": copy.deepcopy(plane), "right": copy.deepcopy(plane)},
        "turntable": {
            "center_mm": [0, 0, 0],
            "axis": [0, 0, 1],
            "diameter_mm": 200,
            "mm_per_revolution": np.pi * 200,
            "command_radians_per_mm": 0.01,
            "commanded_mm_per_revolution": 200 * np.pi,
            "command_direction": "positive",
            "reference_pose_mm": {"x": 195, "y": 0, "z": 20},
            "source": "measured_diameter",
            "quality": {"accepted": True},
        },
        "lidar": {
            "lidar_to_scanner": np.eye(4).tolist(),
            "source": "operator_measured_origin_direction",
            "quality": {"accepted": True, "rms_mm": 2.0, "maximum_rms_mm": 20.0},
        },
        "x_scale_validation": {
            "accepted": True,
            "measured_mm_per_commanded_mm": 1.0,
            "signed_mm_per_commanded_mm": 1.0,
            "command_direction": "positive",
            "expected_mm_per_commanded_mm": 1.0,
            "tolerance_fraction": 0.05,
            "repeatability_rms_mm": 0.2,
            "maximum_repeatability_mm": 3.0,
            "motor_rotation_distance_changed": False,
        },
    }


class CalibrationMathTests(unittest.TestCase):
    def test_checkerboard_is_centered_and_uses_exact_measured_geometry(self):
        points = checkerboard_points()
        self.assertEqual(points.shape, (66, 3))
        np.testing.assert_allclose(points.mean(axis=0), [0, 0, 0], atol=1e-7)
        np.testing.assert_allclose(np.ptp(points, axis=0), [130, 65, 0])

    def test_repeated_views_are_rejected_for_insufficient_diversity(self):
        corners = np.column_stack(
            (
                np.tile(np.arange(11), 6) * 5 + 10,
                np.repeat(np.arange(6), 11) * 5 + 10,
            )
        ).astype(float)
        views = [{"corners": corners.copy(), "image_size": (100, 100)} for _ in range(6)]
        with self.assertRaisesRegex(CalibrationError, "repeated near-identical"):
            validate_view_diversity(views, minimum_views=6, minimum_corner_motion=0)

    def test_centered_rotating_board_has_valid_corner_diversity(self):
        grid = checkerboard_points()[:, :2].astype(float)
        grid[:, 0] /= 500.0
        grid[:, 1] /= 500.0
        views = []
        for angle_deg in (0, 6, 12, 18, 24, 30, 36):
            angle = math.radians(angle_deg)
            distorted = grid.copy()
            distorted[:, 0] *= math.cos(angle)
            distorted[:, 1] += 0.18 * grid[:, 0] * math.sin(angle)
            corners = (distorted + [0.5, 0.5]) * [1280, 960]
            views.append({"corners": corners, "image_size": (1280, 960)})
        metrics = validate_view_diversity(views, minimum_views=6)
        self.assertLess(metrics["center_span"], 1e-12)
        self.assertGreaterEqual(metrics["unique_views"], 6)
        self.assertGreater(metrics["centered_corner_shape_motion_rms"], 0.004)
        self.assertIn("maximum_corner_track_hull", checkerboard_view_metrics(views))

    def test_view_count_is_enforced_before_opencv(self):
        with self.assertRaisesRegex(CalibrationError, "insufficient accepted views"):
            validate_view_diversity([], minimum_views=6)

    def test_robust_plane_fit_discards_outliers(self):
        grid = np.array([[x, y, 25.0] for x in range(8) for y in range(8)], dtype=float)
        points = np.vstack((grid, [[500, 500, -500], [-400, 300, 700]]))
        normal, offset, quality = fit_plane_robust(points, minimum_points=20)
        self.assertAlmostEqual(abs(normal[2]), 1.0, places=6)
        self.assertAlmostEqual(abs(offset), 25.0, places=6)
        self.assertLess(quality["inliers"], quality["samples"])
        self.assertLess(quality["rms_mm"], 0.01)

    def test_lidar_transform_requires_explicit_finite_nonzero_direction(self):
        with self.assertRaises(CalibrationError):
            transform_from_beam([0, 0, 0], [0, 0, 0])
        transform = transform_from_beam([1, 2, 3], [1, 0, 0])
        np.testing.assert_allclose(transform[:3, 3], [1, 2, 3])
        np.testing.assert_allclose(transform[:3, 2], [1, 0, 0])
        self.assertAlmostEqual(np.linalg.det(transform[:3, :3]), 1.0)

    def test_payload_rejects_singular_or_unaccepted_results(self):
        payload = valid_calibration()
        validate_calibration_payload(payload)
        payload["cameras"]["pi"]["intrinsic_matrix"] = np.zeros((3, 3)).tolist()
        with self.assertRaisesRegex(CalibrationError, "singular"):
            validate_calibration_payload(payload)

    def test_payload_rejects_false_checkerboard_pattern_metadata(self):
        payload = valid_calibration()
        payload["checkerboard"]["board_columns"] = 10
        with self.assertRaisesRegex(CalibrationError, "exactly 11x6"):
            validate_calibration_payload(payload)

    def test_payload_requires_reference_for_each_moving_sensor(self):
        for sensor in ("usb", "lidar"):
            with self.subTest(sensor=sensor):
                payload = valid_calibration()
                target = (
                    payload["cameras"]["usb"]
                    if sensor == "usb"
                    else payload["lidar"]
                )
                target["carriage_axis"] = "z"
                target["carriage_direction"] = [0, 0, 1]
                with self.assertRaisesRegex(
                    CalibrationError, "reference_axis_position_mm"
                ):
                    validate_calibration_payload(payload)


class _FakeCV:
    def __init__(self, rms=0.25):
        self.rms = rms

    def calibrateCamera(self, object_points, image_points, image_size, _a, _b):
        count = len(object_points)
        intrinsic = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=float)
        return (
            self.rms,
            intrinsic,
            np.zeros((1, 5)),
            [np.zeros((3, 1)) for _ in range(count)],
            [np.array([[0], [0], [300]], dtype=float) for _ in range(count)],
        )

    @staticmethod
    def projectPoints(points, _rvec, _tvec, _intrinsic, _distortion):
        projected = np.asarray(points)[:, :2].reshape(-1, 1, 2)
        return projected, None


class _Reservation:
    def __init__(self):
        self.held = False

    def acquire(self, blocking=False):
        if self.held:
            return False
        self.held = True
        return True

    def release(self):
        self.held = False


class _Motor:
    connected = True

    def __init__(self):
        self.positions = {"x": 195.0, "y": 0.0, "z": 10.0}
        self.calls = []

    def get_motor_status(self):
        return {
            "positions": dict(self.positions),
            "homed": {"x": True, "y": True, "z": True},
            "moving": {"x": False, "y": False, "z": False},
        }

    def move_motor(self, axis, delta):
        self.positions[axis] += delta
        self.calls.append(("move", axis, delta))
        return True

    def stop_motor(self, axis):
        self.calls.append(("stop", axis))
        return True


class _GPIO:
    simulation = False
    hardware_available = True

    def __init__(self):
        self.state = {"left": False, "right": False}
        self.calls = []

    def laser_on(self, side):
        self.state[side] = True
        self.calls.append(("on", side))
        return True

    def laser_off(self, side):
        self.state[side] = False
        self.calls.append(("off", side))
        return True


class _Camera:
    is_open = True

    @staticmethod
    def capture_jpeg():
        return b"jpeg"


class _Lidar:
    def __init__(self):
        self.output_commands = []

    @staticmethod
    def read_distance_mm():
        return 200.0

    def set_output_enabled(self, enabled, *, timeout_s):
        assert timeout_s > 0
        self.output_commands.append(enabled)
        return True


def service_config():
    return {
        "board_columns": 11,
        "board_rows": 6,
        "square_size_mm": 13,
        "minimum_views": 3,
        "starting_pose_mm": {"x": 195, "y": 0, "z": 20},
        "pose_offsets_mm": [
            {"x": 0, "y": 0, "z": 0},
            {"x": -10, "y": 10.4719755, "z": 10},
            {"x": -20, "y": 20.9439510, "z": 20},
            {"x": -30, "y": 31.4159265, "z": 0},
            {"x": 0, "y": 41.8879020, "z": 20},
            {"x": -30, "y": 52.3598776, "z": 10},
            {"x": -15, "y": 62.8318531, "z": 20},
        ],
        "axis_limits_mm": {
            "x": {"min": 0, "max": 195},
            "y": {"min": 0, "max": 628.32},
            "z": {"min": 0, "max": 270},
        },
        "maximum_camera_rms_px": 1.0,
        "x_scale_tolerance_fraction": 0.05,
        "maximum_x_repeatability_mm": 1.0,
        "motion_timeout_s": 0.1,
        "capture_timeout_s": 0.1,
        "lidar_timeout_s": 0.1,
    }


class CalibrationServiceTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(exist_ok=True)
        self.config_path = SCRATCH / f"hardware-{id(self)}.json"
        self.config_path.write_text(json.dumps({"scan_calibration": {"old": True}}), encoding="utf-8")
        self.motor = _Motor()
        self.gpio = _GPIO()
        self.reservation = _Reservation()
        self.service = GeometricCalibrationService(
            motor_driver=self.motor,
            gpio_driver=self.gpio,
            cameras={"pi": _Camera(), "usb": _Camera()},
            lidar_driver=_Lidar(),
            hardware_reservation=self.reservation,
            store=AtomicCalibrationStore(self.config_path),
            config=service_config(),
            cv_module=_FakeCV(),
            sleep=lambda _seconds: None,
        )

    def tearDown(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)

    def test_preflight_requires_homing_and_explicit_lidar_transform(self):
        readiness = self.service.readiness({})
        self.assertFalse(readiness["ready"])
        self.assertTrue(any("not fully observable" in blocker for blocker in readiness["blockers"]))
        readiness = self.service.readiness(
            {"lidar": {"origin_mm": [0, 0, 0], "direction": [1, 0, 0]}}
        )
        self.assertTrue(readiness["ready"], readiness["blockers"])
        self.motor.get_motor_status = lambda: {
            "positions": self.motor.positions,
            "homed": {"x": False, "y": True, "z": True},
            "moving": {"x": False, "y": False, "z": False},
        }
        self.assertTrue(any("X must be homed" in item for item in self.service.readiness({})["blockers"]))

    def test_passive_preflight_probes_fresh_frames_and_lidar_under_reservation(self):
        options = {"lidar": {"origin_mm": [0, 0, 0], "direction": [1, 0, 0]}}
        result = self.service.preflight(options)
        self.assertTrue(result["ready"], result["blockers"])
        self.assertFalse(self.reservation.held)
        self.service._lidar.read_distance_mm = lambda: None
        result = self.service.preflight(options)
        self.assertFalse(result["ready"])
        self.assertTrue(any("TF-Luna preflight failed" in item for item in result["blockers"]))
        self.assertEqual(self.motor.calls, [])

    def test_trajectory_is_bounded_and_configurable(self):
        poses = self.service._trajectory({"starting_pose_mm": {"x": 190, "y": 5, "z": 20}})
        self.assertEqual(poses[0], {"x": 190.0, "y": 5.0, "z": 20.0})
        self.assertTrue(all(pose["x"] <= 195 for pose in self.service._trajectory({})))
        with self.assertRaisesRegex(CalibrationError, "outside configured limits"):
            self.service._trajectory({"starting_pose_mm": {"x": 206, "y": 0, "z": 10}})

    def test_trajectory_hard_caps_x_even_if_configured_limit_is_unsafe(self):
        self.service._config["axis_limits_mm"]["x"]["max"] = 210
        poses = self.service._trajectory({})
        self.assertTrue(all(pose["x"] <= 195 for pose in poses))
        readiness = self.service.readiness(
            {"lidar": {"origin_mm": [0, 0, 0], "direction": [1, 0, 0]}}
        )
        self.assertFalse(readiness["ready"])
        self.assertIn(
            "calibration X maximum must not exceed 195mm",
            readiness["blockers"],
        )
        with self.assertRaisesRegex(CalibrationError, "outside configured limits"):
            self.service._trajectory(
                {"starting_pose_mm": {"x": 210, "y": 0, "z": 10}}
            )

    def test_failed_starting_framing_blocks_multi_pose_motion(self):
        moved = []
        self.service._move_to = lambda pose: moved.append(dict(pose))
        self.service._capture = lambda name, **_kwargs: name.encode()
        pi_view = {
            "corners": np.zeros((66, 2), dtype=np.float32),
            "image_size": (1280, 960),
            "coverage": 0.2,
        }
        self.service._detect_checkerboard = lambda frame, pose, **_kwargs: (
            {**pi_view, "pose": dict(pose)} if frame == b"pi" else None
        )
        poses = self.service._trajectory({})
        with self.assertRaisesRegex(CalibrationError, "starting pose framing rejected"):
            self.service._capture_checkerboard_views(poses)
        self.assertEqual(moved, [poses[0]])
        self.assertEqual(self.service._lidar.output_commands, [False, True])

    def test_checkerboard_capture_restores_lidar_output_after_failure(self):
        self.service._capture_checkerboard_views_output_suspended = mock.Mock(
            side_effect=CalibrationError("simulated camera failure")
        )
        with self.assertRaisesRegex(CalibrationError, "simulated camera failure"):
            self.service._capture_checkerboard_views(
                [{"x": 195.0, "y": 0.0, "z": 10.0}]
            )
        self.assertEqual(self.service._lidar.output_commands, [False, True])
        self.assertFalse(self.service.status()["lidar_output_suspended"])

    def test_checkerboard_capture_attempts_restore_if_output_suspend_fails(self):
        def set_output(enabled, *, timeout_s):
            self.assertGreater(timeout_s, 0)
            self.service._lidar.output_commands.append(enabled)
            if not enabled:
                self.assertTrue(self.service._lidar_output_restore_required)
            return enabled

        self.service._lidar.set_output_enabled = set_output
        with self.assertRaisesRegex(CalibrationError, "output suspend failed"):
            self.service._capture_checkerboard_views(
                [{"x": 195.0, "y": 0.0, "z": 10.0}]
            )
        self.assertEqual(self.service._lidar.output_commands, [False, True])
        self.assertFalse(self.service.status()["lidar_output_suspended"])
        self.assertFalse(self.service._lidar_output_restore_required)

    def test_checkerboard_capture_restores_lidar_output_on_cancellation(self):
        def cancel(_poses):
            self.service._cancel.set()
            raise CalibrationCancelled("calibration cancelled")

        self.service._capture_checkerboard_views_output_suspended = cancel
        with self.assertRaises(CalibrationCancelled):
            self.service._capture_checkerboard_views(
                [{"x": 195.0, "y": 0.0, "z": 10.0}]
            )
        self.assertEqual(self.service._lidar.output_commands, [False, True])
        self.assertFalse(self.service.status()["lidar_output_suspended"])

    def test_framing_retries_after_one_timeout_and_accepts_first_exact_view(self):
        view = {
            "corners": np.zeros((66, 2), dtype=np.float32),
            "image_size": (1280, 960),
            "coverage": 0.2,
            "pose": {"x": 195, "y": 0, "z": 10},
        }
        self.service._capture = mock.Mock(return_value=b"usb")
        self.service._detect_checkerboard = mock.Mock(
            side_effect=[
                CheckerboardDetectionTimeout("checkerboard detection timed out"),
                view,
            ]
        )

        candidate, timeouts, exhausted, rejection_reasons = (
            self.service._capture_checkerboard_candidate(
                "usb",
                view["pose"],
                frames_per_pose=3,
                pose_deadline=time.monotonic() + 1,
            )
        )

        self.assertIs(candidate, view)
        self.assertEqual(timeouts, 1)
        self.assertFalse(exhausted)
        self.assertEqual(rejection_reasons, [])
        self.assertEqual(self.service._capture.call_count, 2)
        self.assertEqual(self.service._detect_checkerboard.call_count, 2)

    def test_starting_framing_fails_after_all_configured_frames_time_out(self):
        pose = {"x": 195.0, "y": 0.0, "z": 10.0}
        view = {
            "corners": np.zeros((66, 2), dtype=np.float32),
            "image_size": (1280, 960),
            "coverage": 0.2,
            "pose": pose,
        }
        attempts = {"usb": 0}
        self.service._config.update(
            fresh_frames_per_pose=3,
            checkerboard_pose_timeout_s=1,
        )
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda name, **_kwargs: name.encode()

        def detect(frame, _pose, **_kwargs):
            if frame == b"pi":
                return view
            attempts["usb"] += 1
            raise CheckerboardDetectionTimeout("checkerboard detection timed out")

        self.service._detect_checkerboard = detect
        with self.assertRaisesRegex(
            CalibrationError, r"usb: 3 detector timeout\(s\)"
        ):
            self.service._capture_checkerboard_views([pose])
        self.assertEqual(attempts["usb"], 3)

    def test_checkerboard_retries_obey_overall_pose_deadline(self):
        self.service._config.update(
            checkerboard_timeout_s=0.03,
            capture_timeout_s=0.03,
        )
        self.service._capture = lambda _name, **_kwargs: b"jpeg"
        attempts = 0

        def bounded_timeout(_frame, _pose, *, timeout_s):
            nonlocal attempts
            attempts += 1
            time.sleep(timeout_s)
            raise CheckerboardDetectionTimeout("checkerboard detection timed out")

        self.service._detect_checkerboard = bounded_timeout
        started = time.monotonic()
        candidate, timeouts, exhausted, rejection_reasons = (
            self.service._capture_checkerboard_candidate(
                "usb",
                {"x": 195, "y": 0, "z": 10},
                frames_per_pose=20,
                pose_deadline=started + 0.055,
            )
        )
        elapsed = time.monotonic() - started

        self.assertIsNone(candidate)
        self.assertEqual(timeouts, attempts)
        self.assertTrue(exhausted)
        self.assertEqual(rejection_reasons, [])
        self.assertLessEqual(attempts, 2)
        self.assertLess(elapsed, 0.15)

    def test_capture_cancellation_near_deadline_is_not_converted_to_timeout(self):
        def cancel_during_capture(_name, **_kwargs):
            self.service._cancel.set()
            time.sleep(0.01)
            raise CalibrationCancelled("calibration cancelled")

        self.service._capture = cancel_during_capture
        with self.assertRaises(CalibrationCancelled):
            self.service._capture_checkerboard_candidate(
                "usb",
                {"x": 195, "y": 0, "z": 10},
                frames_per_pose=1,
                pose_deadline=time.monotonic() + 0.005,
            )

    def test_cancel_at_last_camera_last_pose_is_checked_before_diversity(self):
        pose = {"x": 195.0, "y": 0.0, "z": 10.0}
        view = {
            "corners": np.zeros((66, 2), dtype=np.float32),
            "image_size": (1280, 960),
            "coverage": 0.2,
            "pose": pose,
        }
        self.service._config.update(
            fresh_frames_per_pose=1,
            checkerboard_pose_timeout_s=1,
        )
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda name, **_kwargs: name.encode()

        def cancel_on_last_camera(frame, _pose, **_kwargs):
            if frame == b"usb":
                self.service._cancel.set()
            return view

        self.service._detect_checkerboard = cancel_on_last_camera
        with (
            mock.patch(
                "software.api.geometric_calibration.validate_view_diversity"
            ) as diversity,
            self.assertRaises(CalibrationCancelled),
        ):
            self.service._capture_checkerboard_views([pose])
        diversity.assert_not_called()

    def test_intrinsic_solver_preserves_distortion_and_rejects_bad_rms(self):
        points = checkerboard_points()[:, :2]
        views = [
            {"corners": points.copy(), "image_size": (640, 480)}
            for _ in range(3)
        ]
        result = self.service._calibrate_camera_intrinsics(views)
        self.assertEqual(len(result["distortion_coefficients"]), 5)
        self.assertTrue(result["quality"]["accepted"])
        self.service._cv.rms = 2.0
        with self.assertRaisesRegex(CalibrationError, "exceeds"):
            self.service._calibrate_camera_intrinsics(views)

    def test_calibration_detector_accepts_sb_full_frame_corners_and_records_glare(self):
        image = np.zeros((960, 1280, 3), dtype=np.uint8)
        corners = np.array(
            [[[200 + column * 70, 250 + row * 70]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with mock.patch(
            "software.api.geometric_calibration.find_checkerboard_bounded",
            return_value={
                "found": True,
                "pattern": (11, 6),
                "corners": corners,
                "method": "sb",
                "glare_masked": True,
            },
        ):
            view = self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )
        self.assertIsNotNone(view)
        self.assertEqual(view["image_size"], (1280, 960))
        self.assertEqual(view["detection_method"], "sb")
        self.assertTrue(view["glare_masked"])

    def test_calibration_accepts_exact_board_with_2_7_percent_corner_margin(self):
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        corners = np.array(
            [[[27 + column * 80, 100 + row * 100]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with mock.patch(
            "software.api.geometric_calibration.find_checkerboard_bounded",
            return_value={
                "found": True,
                "pattern": (11, 6),
                "corners": corners,
                "method": "sb",
                "glare_masked": False,
            },
        ):
            view = self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )

        self.assertAlmostEqual(view["minimum_frame_margin"], 0.027, places=6)
        self.assertEqual(view["frame_margins"]["left"], view["minimum_frame_margin"])

    def test_calibration_frame_margin_remains_configurable(self):
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        corners = np.array(
            [[[27 + column * 80, 100 + row * 100]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._config["minimum_frame_margin"] = 0.03
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with (
            mock.patch(
                "software.api.geometric_calibration.find_checkerboard_bounded",
                return_value={
                    "found": True,
                    "pattern": (11, 6),
                    "corners": corners,
                    "method": "sb",
                },
            ),
            self.assertRaisesRegex(
                CheckerboardDetectionRejected,
                r"left corner margin 0\.0270.*minimum_frame_margin 0\.0300",
            ),
        ):
            self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )

    def test_calibration_rejects_exact_board_too_close_to_frame_edge(self):
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        corners = np.array(
            [[[19 + column * 80, 100 + row * 100]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with mock.patch(
            "software.api.geometric_calibration.find_checkerboard_bounded",
            return_value={
                "found": True,
                "pattern": (11, 6),
                "corners": corners,
                "method": "sb",
            },
        ):
            with self.assertRaisesRegex(
                CheckerboardDetectionRejected,
                r"left corner margin 0\.0190.*minimum_frame_margin 0\.0200",
            ):
                self.service._detect_checkerboard(
                    b"jpeg", {"x": 195, "y": 0, "z": 10}
                )

    def test_calibration_reports_low_coverage_separately_from_frame_margin(self):
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        corners = np.array(
            [[[100 + column * 4, 100 + row * 4]]
             for row in range(6) for column in range(11)],
            dtype=np.float32,
        )
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: image
        with (
            mock.patch(
                "software.api.geometric_calibration.find_checkerboard_bounded",
                return_value={
                    "found": True,
                    "pattern": (11, 6),
                    "corners": corners,
                    "method": "classic",
                },
            ),
            self.assertRaisesRegex(
                CheckerboardDetectionRejected,
                r"board coverage 0\.0008.*minimum_board_coverage 0\.0300",
            ),
        ):
            self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )

    def test_starting_framing_reports_detection_and_coverage_rejections(self):
        pose = {"x": 195.0, "y": 0.0, "z": 10.0}
        self.service._config.update(fresh_frames_per_pose=1)
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda name, **_kwargs: name.encode()

        def reject(frame, _pose, **_kwargs):
            if frame == b"pi":
                raise CheckerboardDetectionRejected(
                    "board coverage 0.0120 is below minimum_board_coverage 0.0300"
                )
            raise CheckerboardDetectionRejected(
                "IR glare mask overlaps a detected checkerboard corner"
            )

        self.service._detect_checkerboard = reject
        with self.assertRaisesRegex(
            CalibrationError,
            r"pi: board coverage 0\.0120.*usb: IR glare mask overlaps",
        ):
            self.service._capture_checkerboard_views([pose])
        self.assertIn(
            "board coverage",
            self.service.status()["last_checkerboard_rejection"]["pi"],
        )
        self.assertIn(
            "IR glare",
            self.service.status()["last_checkerboard_rejection"]["usb"],
        )

    def test_calibration_detector_surfaces_bounded_detection_timeout(self):
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: np.zeros(
            (960, 1280, 3), dtype=np.uint8
        )
        with mock.patch(
            "software.api.geometric_calibration.find_checkerboard_bounded",
            return_value={"found": False, "timed_out": True},
        ):
            with self.assertRaisesRegex(CalibrationError, "timed out"):
                self.service._detect_checkerboard(
                    b"jpeg", {"x": 195, "y": 0, "z": 10}
                )

    def test_calibration_rejects_detector_result_for_different_pattern(self):
        self.service._cv.IMREAD_COLOR = 1
        self.service._cv.imdecode = lambda _data, _mode: np.zeros(
            (960, 1280, 3), dtype=np.uint8
        )
        false_corners = np.zeros((60, 1, 2), dtype=np.float32)
        with (
            mock.patch(
                "software.api.geometric_calibration.find_checkerboard_bounded",
                return_value={
                    "found": True,
                    "pattern": (10, 6),
                    "corners": false_corners,
                    "method": "sb",
                },
            ),
            self.assertRaisesRegex(
                CheckerboardDetectionRejected,
                r"detected checkerboard pattern \(10, 6\), expected \(11, 6\)",
            ),
        ):
            self.service._detect_checkerboard(
                b"jpeg", {"x": 195, "y": 0, "z": 10}
            )

    def test_x_scale_is_validated_without_changing_rotation_distance(self):
        self.service._motion_model.update(
            x_mm_per_commanded_mm=-1.0,
            x_direction="negative",
            x_translation_rms_mm=0.2,
        )
        result = self.service._validate_x_scale()
        self.assertTrue(result["accepted"])
        self.assertEqual(result["signed_mm_per_commanded_mm"], -1.0)
        self.assertFalse(result["motor_rotation_distance_changed"])
        self.service._motion_model["x_mm_per_commanded_mm"] = -1.2
        with self.assertRaisesRegex(CalibrationError, "rotation_distance was not changed"):
            self.service._validate_x_scale()

    def test_scanner_frame_pose_math_and_extrinsic_average_are_consistent(self):
        self.service._reference_pose = {"x": 195, "y": 0, "z": 10}
        self.service._motion_model.update(
            x_mm_per_commanded_mm=1.0,
            y_radians_per_commanded_mm=0.01,
        )
        transform = self.service._board_to_scanner({"x": 185, "y": 0, "z": 10})
        np.testing.assert_allclose(transform[:3, 3], [-10, 0, 0])
        np.testing.assert_allclose(transform[:3, :3], [[0, 0, 1], [1, 0, 0], [0, 1, 0]])
        shifted = transform.copy()
        shifted[:3, 3] += [0, 2, 0]
        average, translation_rms, rotation_rms = self.service._average_transforms(
            [transform, shifted]
        )
        np.testing.assert_allclose(average[:3, 3], [-10, 1, 0])
        self.assertAlmostEqual(translation_rms, 1.0)
        self.assertAlmostEqual(rotation_rms, 0.0)

    def _synthetic_motion_views(self, x_scale, y_scale):
        poses = self.service._trajectory({})
        self.service._reference_pose = dict(poses[0])
        camera_to_scanner = {
            "pi": np.array(
                [
                    [0, -1, 0, 80],
                    [1, 0, 0, -35],
                    [0, 0, 1, 260],
                    [0, 0, 0, 1],
                ],
                dtype=float,
            ),
            "usb": np.array(
                [
                    [1, 0, 0, -60],
                    [0, 0, -1, 45],
                    [0, 1, 0, 220],
                    [0, 0, 0, 1],
                ],
                dtype=float,
            ),
        }
        views = {"pi": [], "usb": []}
        for name in ("pi", "usb"):
            for pose in poses:
                scanner_from_board = self.service._board_transform(
                    pose, x_scale=x_scale, y_scale=y_scale
                )
                scanner_from_camera = camera_to_scanner[name].copy()
                if name == "usb":
                    scanner_from_camera[:3, 3] += [
                        0,
                        0,
                        pose["z"] - poses[0]["z"],
                    ]
                views[name].append(
                    {
                        "pose": dict(pose),
                        "board_to_camera": (
                            np.linalg.inv(scanner_from_camera) @ scanner_from_board
                        ),
                    }
                )
        return views, camera_to_scanner

    def test_axis_model_recovers_both_command_signs_and_moving_usb(self):
        expected_y = 2.0 / 200.0
        for x_sign in (-1.0, 1.0):
            for y_sign in (-1.0, 1.0):
                with self.subTest(x_sign=x_sign, y_sign=y_sign):
                    views, expected_cameras = self._synthetic_motion_views(
                        x_sign, y_sign * expected_y * 1.02
                    )
                    model = self.service._estimate_motion_model(views)
                    self.service._motion_model = model
                    self.assertAlmostEqual(
                        model["x_mm_per_commanded_mm"], x_sign, places=5
                    )
                    self.assertAlmostEqual(
                        model["y_radians_per_commanded_mm"],
                        y_sign * expected_y * 1.02,
                        places=6,
                    )
                    self.assertGreater(
                        model["candidate_residuals"]["x"][
                            "direction_score_ratio"
                        ],
                        2,
                    )
                    for name in ("pi", "usb"):
                        camera = {
                            "quality": {
                                "accepted": True,
                                "rms_px": 0.1,
                                "maximum_rms_px": 1.0,
                            }
                        }
                        result = self.service._calibrate_camera_extrinsics(
                            name, views[name], camera, {}
                        )
                        np.testing.assert_allclose(
                            result["camera_to_scanner"],
                            expected_cameras[name],
                            atol=1e-5,
                        )

    def test_axis_model_rejects_degenerate_and_wrong_scale_trajectories(self):
        expected_y = 2.0 / 200.0
        views, _ = self._synthetic_motion_views(1.0, expected_y)
        for camera_views in views.values():
            reference_rotation = camera_views[0]["board_to_camera"][:3, :3].copy()
            for view in camera_views:
                view["board_to_camera"][:3, :3] = reference_rotation
        with self.assertRaisesRegex(CalibrationError, "Y rotation direction is ambiguous"):
            self.service._estimate_motion_model(views)

        views, _ = self._synthetic_motion_views(1.0, expected_y * 1.2)
        with self.assertRaisesRegex(CalibrationError, "validation boundary"):
            self.service._estimate_motion_model(views)

    def test_axis_and_extrinsic_fit_reject_single_pnp_outlier(self):
        expected_y = 2.0 / 200.0
        views, expected_cameras = self._synthetic_motion_views(-1.0, -expected_y)
        outlier = views["pi"][3]["board_to_camera"]
        outlier[:3, 3] += [40, -25, 30]
        outlier[:3, :3] = (
            self.service._rotation_z(math.radians(12)) @ outlier[:3, :3]
        )

        model = self.service._estimate_motion_model(views)
        self.service._motion_model = model
        self.assertAlmostEqual(model["x_mm_per_commanded_mm"], -1.0, places=4)
        self.assertAlmostEqual(
            model["y_radians_per_commanded_mm"], -expected_y, places=6
        )
        result = self.service._calibrate_camera_extrinsics(
            "pi",
            views["pi"],
            {
                "quality": {
                    "accepted": True,
                    "rms_px": 0.1,
                    "maximum_rms_px": 1.0,
                }
            },
            {},
        )
        np.testing.assert_allclose(
            result["camera_to_scanner"], expected_cameras["pi"], atol=1e-4
        )
        self.assertEqual(result["quality"]["robust_pnp_inliers"], 6)

    def test_lidar_geometry_rejects_unobservable_beam_direction(self):
        self.service._move_to = lambda _pose: None
        poses = self.service._trajectory({})
        with self.assertRaisesRegex(CalibrationError, "not observable"):
            self.service._calibrate_lidar(
                poses,
                {},
                {"origin_mm": [0, 0, 0], "direction": [0, 0, 1]},
            )

    def test_laser_capture_error_always_forces_both_lasers_off(self):
        self.service._move_to = lambda _pose: None
        self.service._capture = lambda _name: b"jpeg"
        self.service._laser_board_points = mock.Mock(side_effect=CalibrationError("bad line"))
        with self.assertRaisesRegex(CalibrationError, "bad line"):
            self.service._calibrate_lasers(
                [{"x": 195, "y": 0, "z": 10}],
                {"cameras": {}},
            )
        self.assertFalse(any(self.gpio.state.values()))
        self.assertIn(("on", "left"), self.gpio.calls)
        self.assertIn(("off", "left"), self.gpio.calls)

    def test_cancellation_during_blocked_hardware_call_is_bounded_and_cleans_up(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked_capture():
            entered.set()
            release.wait(1)
            return b"late"

        self.service._cameras["pi"].capture_jpeg = blocked_capture
        errors = []

        def invoke():
            try:
                self.service._capture("pi")
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=invoke)
        thread.start()
        self.assertTrue(entered.wait(0.5))
        self.service.cancel()
        thread.join(0.5)
        release.set()
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(errors[0], CalibrationCancelled)
        self.assertFalse(any(self.gpio.state.values()))
        self.assertIn(("stop", "all"), self.motor.calls)

    def test_hardware_call_times_out_without_infinite_wait(self):
        started = time.monotonic()
        with self.assertRaisesRegex(CalibrationError, "timed out"):
            self.service._hardware_call("blocked", lambda: time.sleep(1), 0.03)
        self.assertLess(time.monotonic() - started, 0.3)


class AtomicCalibrationStoreTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(exist_ok=True)
        self.path = SCRATCH / f"atomic-{id(self)}.json"
        self.original = {"scan_calibration": {"version": "old"}, "other": 7}
        self.path.write_text(json.dumps(self.original), encoding="utf-8")
        self.store = AtomicCalibrationStore(self.path)

    def tearDown(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)

    def test_atomic_save_report_and_rollback(self):
        calibration = valid_calibration()
        report = {"calibration": calibration, "metrics": {"accepted": True}}
        self.store.save(calibration, report)
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["other"], 7)
        self.assertEqual(persisted["scan_calibration"], calibration)
        self.assertEqual(self.store.report()["metrics"]["accepted"], True)
        restored = self.store.rollback()
        self.assertEqual(restored, {"version": "old"})
        self.assertEqual(json.loads(self.path.read_text())["scan_calibration"], {"version": "old"})

    def test_first_save_creates_runtime_state_without_tracked_config(self):
        self.path.unlink()
        calibration = valid_calibration()

        self.store.save(calibration, {"calibration": calibration})

        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["schema_version"], 1)
        self.assertEqual(persisted["scan_calibration"], calibration)

    def test_validation_failure_never_modifies_config_or_backup(self):
        invalid = valid_calibration()
        invalid["lidar"]["quality"]["accepted"] = False
        before = self.path.read_bytes()
        with self.assertRaises(CalibrationError):
            self.store.save(invalid, {"calibration": invalid})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.store.backup_path.exists())

    def test_persistence_failure_leaves_primary_config_unchanged(self):
        before = self.path.read_bytes()
        with mock.patch(
            "software.api.geometric_calibration.os.replace",
            side_effect=OSError("simulated replace failure"),
        ):
            with self.assertRaisesRegex(OSError, "simulated replace failure"):
                self.store.save(valid_calibration(), {"calibration": valid_calibration()})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_suffix(".json.new").exists())


if __name__ == "__main__":
    unittest.main()
