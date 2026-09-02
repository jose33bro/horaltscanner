import copy
import json
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
    GeometricCalibrationService,
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
        "cameras": {"pi": copy.deepcopy(camera), "usb": copy.deepcopy(camera)},
        "laser_planes": {"left": copy.deepcopy(plane), "right": copy.deepcopy(plane)},
        "turntable": {
            "center_mm": [0, 0, 0],
            "axis": [0, 0, 1],
            "diameter_mm": 200,
            "mm_per_revolution": np.pi * 200,
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
        corners = np.array([[10, 10], [20, 10], [10, 20], [20, 20]], dtype=float)
        views = [{"corners": corners.copy(), "image_size": (100, 100)} for _ in range(6)]
        with self.assertRaisesRegex(CalibrationError, "position diversity"):
            validate_view_diversity(views, minimum_views=6)

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
        self.positions = {"x": 185.0, "y": 0.0, "z": 25.0}
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
    @staticmethod
    def read_distance_mm():
        return 200.0


def service_config():
    return {
        "columns": 11,
        "rows": 6,
        "square_size_mm": 13,
        "minimum_views": 3,
        "starting_pose_mm": {"x": 185, "y": 0, "z": 25},
        "pose_offsets_mm": [
            {"x": -10, "y": 0, "z": 0},
            {"x": 0, "y": 10, "z": 0},
            {"x": 10, "y": 20, "z": 0},
        ],
        "axis_limits_mm": {
            "x": {"min": 0, "max": 210},
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
        poses = self.service._trajectory({"starting_pose_mm": {"x": 190, "y": 5, "z": 30}})
        self.assertEqual(poses[0], {"x": 180.0, "y": 5.0, "z": 30.0})
        with self.assertRaisesRegex(CalibrationError, "outside configured limits"):
            self.service._trajectory({"starting_pose_mm": {"x": 209, "y": 0, "z": 25}})

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

    def test_x_scale_is_validated_without_changing_rotation_distance(self):
        views = [
            {"pose": {"x": x}, "tvec": np.array([[x], [0], [300]])}
            for x in (175.0, 185.0, 195.0)
        ]
        result = self.service._validate_x_scale(views, {})
        self.assertTrue(result["accepted"])
        self.assertFalse(result["motor_rotation_distance_changed"])
        views[-1]["tvec"] = np.array([[230], [0], [300]])
        with self.assertRaisesRegex(CalibrationError, "rotation_distance was not changed"):
            self.service._validate_x_scale(views, {})

    def test_scanner_frame_pose_math_and_extrinsic_average_are_consistent(self):
        self.service._reference_pose = {"x": 185, "y": 0, "z": 25}
        transform = self.service._board_to_scanner({"x": 195, "y": 0, "z": 25})
        np.testing.assert_allclose(transform[:3, 3], [10, 0, 0])
        np.testing.assert_allclose(transform[:3, :3], [[0, 0, 1], [1, 0, 0], [0, 1, 0]])
        shifted = transform.copy()
        shifted[:3, 3] += [0, 2, 0]
        average, translation_rms, rotation_rms = self.service._average_transforms(
            [transform, shifted]
        )
        np.testing.assert_allclose(average[:3, 3], [10, 1, 0])
        self.assertAlmostEqual(translation_rms, 1.0)
        self.assertAlmostEqual(rotation_rms, 0.0)

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
                [{"x": 185, "y": 0, "z": 25}],
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
