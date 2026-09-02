import threading
import time
import unittest
from unittest import mock

import numpy as np

from software.api.scanner_engine import (
    ReconstructionEngine,
    ScanData,
    ScanPreflightError,
    ScanSession,
    _CV2_AVAILABLE,
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


class _FakeMotor:
    def __init__(self, homed=True, limits=(0.0, 10.0)):
        self.connected = True
        self.positions = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.homed = {axis: homed for axis in self.positions}
        self.limits = limits
        self.calls = []

    def get_motor_status(self):
        return {
            "positions": dict(self.positions),
            "homed": dict(self.homed),
            "moving": {axis: False for axis in self.positions},
        }

    def move_motor(self, axis, distance):
        self.calls.append(("move", axis, distance))
        self.positions[axis] += distance
        return True

    def get_motor_limits(self, axis):
        return self.limits if axis == "x" else (0.0, 10.0)

    def home_motor(self, axis):
        self.calls.append(("home", axis))
        self.positions[axis] = self.limits[0]
        self.homed[axis] = True
        return True

    def move_motor_to(self, axis, target):
        return self.move_motor(axis, target - self.positions[axis])

    def invalidate_motor_position(self, axis):
        self.calls.append(("invalidate", axis))
        self.homed[axis] = False

    def stop_motor(self, axis="all"):
        self.calls.append(("stop", axis))
        return True


class _FakeGPIO:
    simulation = False
    hardware_available = True

    def __init__(self):
        self.calls = []
        self.state = {"left": False, "right": False}

    def laser_on(self, side):
        self.calls.append(("on", side))
        self.state[side] = True
        return True

    def laser_off(self, side):
        self.calls.append(("off", side))
        self.state[side] = False
        return True


class _FakeCamera:
    is_open = True
    last_error = None

    def __init__(self, block_after=None):
        self.calls = 0
        self.block_after = block_after

    def capture_jpeg(self):
        self.calls += 1
        if self.block_after is not None and self.calls > self.block_after:
            time.sleep(0.3)
        return b"jpeg"


class _FakeLidar:
    connected = True

    def __init__(self, distance=100.0):
        self.distance = distance

    def connect(self):
        self.connected = True
        return True

    def read_distance_mm(self):
        return self.distance


class _BlockingLidar(_FakeLidar):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def read_distance_mm(self):
        self.entered.set()
        self.release.wait(1)
        return self.distance


class _FakeReservation:
    def __init__(self):
        self._lock = threading.Lock()

    def acquire(self, blocking=True):
        return self._lock.acquire(blocking=blocking)

    def release(self):
        self._lock.release()

    @property
    def locked(self):
        return self._lock.locked()


VALID_CALIBRATION = {
    "checkerboard": {
        "board_columns": 11,
        "board_rows": 6,
        "square_size_mm": 13,
    },
    "cameras": {
        "pi": {
            "intrinsic_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "distortion_coefficients": [0, 0, 0, 0, 0],
            "camera_to_scanner": np.eye(4).tolist(),
            "quality": {"accepted": True, "rms_px": 0.1, "maximum_rms_px": 1.0, "extrinsic_translation_rms_mm": 0.1, "maximum_extrinsic_rms_mm": 5.0, "extrinsic_rotation_rms_deg": 0.1, "maximum_extrinsic_rms_deg": 3.0},
        },
        "usb": {
            "intrinsic_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "distortion_coefficients": [0, 0, 0, 0, 0],
            "camera_to_scanner": np.eye(4).tolist(),
            "carriage_axis": "z",
            "carriage_direction": [0, 0, 1],
            "quality": {"accepted": True, "rms_px": 0.1, "maximum_rms_px": 1.0, "extrinsic_translation_rms_mm": 0.1, "maximum_extrinsic_rms_mm": 5.0, "extrinsic_rotation_rms_deg": 0.1, "maximum_extrinsic_rms_deg": 3.0},
        },
    },
    "laser_planes": {
        "left": {"normal": [0, 0, 1], "offset_mm": -100, "quality": {"accepted": True, "rms_mm": 0.1, "maximum_rms_mm": 2.0}},
        "right": {"normal": [0, 0, 1], "offset_mm": -100, "quality": {"accepted": True, "rms_mm": 0.1, "maximum_rms_mm": 2.0}},
    },
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
        "carriage_axis": "z",
        "carriage_direction": [0, 0, 1],
        "min_distance_mm": 20,
        "max_distance_mm": 1000,
        "source": "operator_measured_origin_direction",
        "quality": {"accepted": True, "rms_mm": 1.0, "maximum_rms_mm": 20.0},
    },
    "x_scale_validation": {
        "accepted": True,
        "measured_mm_per_commanded_mm": 1.0,
        "repeatability_rms_mm": 0.1,
        "maximum_repeatability_mm": 3.0,
        "motor_rotation_distance_changed": False,
    },
}

SAFE_CONFIG = {
    "scan_pose_camera": "pi",
    "center_x_before_scan": True,
    "rotation_steps": 1,
    "z_levels": 1,
    "rotation_step_mm": 1,
    "z_step_mm": 1,
    "axis_limits_mm": {
        "x": {"min": 0, "max": 10},
        "y": {"min": 0, "max": 10},
        "z": {"min": 0, "max": 10},
    },
    "settle_ms": 1,
    "laser_settle_ms": 1,
    "lidar_samples_per_pose": 1,
    "capture_timeout_s": 0.1,
    "lidar_timeout_s": 0.1,
    "motion_timeout_s": 0.1,
    "max_triangulation_distance_mm": 1000,
}


class _SequencingSession(ScanSession):
    def _extract_points(
        self,
        camera_name,
        laser_side,
        ambient_jpeg,
        laser_jpeg,
        trajectory_origin,
    ):
        return [[1.0, 2.0, 3.0]]


class RealScanSessionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("software.api.scanner_engine._CV2_AVAILABLE", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_session(
        self,
        *,
        homed=True,
        calibration=VALID_CALIBRATION,
        cameras=None,
        config=None,
        lidar=None,
        saved_pose=None,
        laser_line_analyzer=None,
        hardware_reservation=None,
    ):
        self.motor = _FakeMotor(homed=homed)
        self.gpio = _FakeGPIO()
        self.cameras = cameras or {"pi": _FakeCamera(), "usb": _FakeCamera()}
        return _SequencingSession(
            simulation=False,
            motor_driver=self.motor,
            gpio_driver=self.gpio,
            cameras=self.cameras,
            lidar_driver=lidar or _FakeLidar(),
            config=config or SAFE_CONFIG,
            calibration=calibration,
            saved_poses_provider=lambda: {
                "pi": saved_pose or {"x": 0.0, "y": 0.0, "z": 0.0}
            },
            laser_line_analyzer=laser_line_analyzer,
            hardware_reservation=hardware_reservation,
        )

    @staticmethod
    def wait_for_completion(session):
        deadline = time.time() + 2
        while session.status()["scanning"] and time.time() < deadline:
            time.sleep(0.01)
        return session.status()

    def test_real_scan_sequences_both_lasers_both_cameras_and_lidar(self):
        session = self.make_session()

        session.start()
        status = self.wait_for_completion(session)

        self.assertEqual(status["phase"], "complete")
        self.assertEqual(status["mode"], "real")
        self.assertEqual(status["camera_frames"], 6)
        self.assertGreaterEqual(status["lidar_samples"], 1)
        self.assertEqual(status["points"], 5)
        on_calls = [call for call in self.gpio.calls if call[0] == "on"]
        self.assertEqual(on_calls, [("on", "left"), ("on", "right")])
        self.assertEqual(self.cameras["pi"].calls, 4)
        self.assertEqual(self.cameras["usb"].calls, 4)
        self.assertFalse(any(self.gpio.state.values()))

    def test_real_scan_reuses_shared_laser_line_analysis(self):
        analyzed = []
        session = self.make_session(
            laser_line_analyzer=lambda frame: (
                analyzed.append(frame)
                or {"analysis_available": True, "line_detected": True}
            )
        )

        session.start()
        status = self.wait_for_completion(session)

        self.assertEqual(status["phase"], "complete")
        self.assertEqual(len(analyzed), 4)
        self.assertEqual(status["laser_detections"], {"left": 2, "right": 2})

    def test_probe_captures_both_cameras_and_rejects_out_of_range_lidar(self):
        session = self.make_session(lidar=_FakeLidar(distance=1500.0))

        readiness = session.readiness(probe=True)

        self.assertFalse(readiness["ready"])
        self.assertTrue(any("outside calibrated range" in item for item in readiness["blockers"]))
        self.assertEqual(self.cameras["pi"].calls, 1)
        self.assertEqual(self.cameras["usb"].calls, 1)

    def test_missing_homing_is_an_actionable_blocker(self):
        session = self.make_session(homed=False)

        readiness = session.readiness()

        self.assertFalse(readiness["ready"])
        self.assertTrue(any("Axis Y must be homed" in item for item in readiness["blockers"]))
        with self.assertRaises(ScanPreflightError):
            session.start()

    def test_missing_calibration_never_falls_back_to_simulation(self):
        session = self.make_session(calibration={})

        with self.assertRaises(ScanPreflightError):
            session.start()

        status = session.status()
        self.assertEqual(status["mode"], "real")
        self.assertFalse(status["simulation"])
        self.assertEqual(status["points"], 0)

    def test_saved_pose_and_all_axes_are_checked_against_limits(self):
        session = self.make_session(saved_pose={"x": 0.0, "y": 11.0, "z": 0.0})

        readiness = session.readiness()

        self.assertFalse(readiness["ready"])
        self.assertTrue(any("Axis Y scan path" in item for item in readiness["blockers"]))

    def test_real_scan_automatically_homes_and_centers_x(self):
        session = self.make_session(
            homed=False,
            saved_pose={"x": 9.0, "y": 0.0, "z": 0.0},
        )
        self.motor.homed["y"] = True
        self.motor.homed["z"] = True

        session.start()
        status = self.wait_for_completion(session)

        self.assertEqual(status["phase"], "complete")
        self.assertEqual(self.motor.calls[:2], [("home", "x"), ("move", "x", 5.0)])
        self.assertEqual(status["motor_preparation"]["target_mm"], 5.0)
        self.assertEqual(status["motor_preparation"]["actual_mm"], 5.0)
        self.assertFalse(
            any(call == ("move", "x", 4.0) for call in self.motor.calls),
            "The saved X pose must not move X away from its automatic center",
        )

    def test_invalid_x_limits_block_start_before_any_motion(self):
        config = {
            **SAFE_CONFIG,
            "axis_limits_mm": {
                **SAFE_CONFIG["axis_limits_mm"],
                "x": {"min": 10, "max": 0},
            },
        }
        session = self.make_session(config=config)

        with self.assertRaises(ScanPreflightError):
            session.start()

        self.assertFalse(any(call[0] in {"home", "move"} for call in self.motor.calls))

    def test_x_center_failure_stops_and_invalidates_position(self):
        session = self.make_session()
        self.motor.move_motor_to = lambda axis, target: False

        with self.assertRaisesRegex(ScanPreflightError, "centering was rejected"):
            session.start()

        self.assertIn(("stop", "x"), self.motor.calls)
        self.assertIn(("invalidate", "x"), self.motor.calls)
        self.assertFalse(self.motor.homed["x"])

    def test_rejected_emergency_stop_quarantines_x_until_manual_home(self):
        session = self.make_session()
        self.motor.move_motor_to = lambda axis, target: False
        self.motor.stop_motor = lambda axis="all": (
            self.motor.calls.append(("stop", axis)) or False
        )

        with self.assertRaises(ScanPreflightError):
            session.start()
        calls_after_failure = list(self.motor.calls)
        with self.assertRaisesRegex(ScanPreflightError, "emergency stop was rejected"):
            session.start()

        self.assertEqual(self.motor.calls, calls_after_failure)
        session.clear_motion_fault("x")

    def test_x_homing_timeout_returns_promptly_and_stays_invalid(self):
        config = {**SAFE_CONFIG, "x_homing_timeout_s": 0.02}
        reservation = _FakeReservation()
        session = self.make_session(
            config=config,
            hardware_reservation=reservation,
        )
        release_home = threading.Event()
        home_returned = threading.Event()

        def blocked_home(axis):
            self.motor.calls.append(("home", axis))
            release_home.wait(1)
            self.motor.positions[axis] = self.motor.limits[0]
            self.motor.homed[axis] = True
            home_returned.set()
            return True

        self.motor.home_motor = blocked_home
        started = time.monotonic()
        with self.assertRaisesRegex(ScanPreflightError, "timed out"):
            session.start()
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.2)
        self.assertIn(("stop", "x"), self.motor.calls)
        self.assertTrue(reservation.locked)
        release_home.set()
        self.assertTrue(home_returned.wait(0.5))
        deadline = time.monotonic() + 0.5
        while self.motor.homed["x"] and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(self.motor.homed["x"])
        deadline = time.monotonic() + 0.5
        while reservation.locked and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(reservation.locked)

    def test_runtime_move_guard_rejects_target_outside_limits(self):
        session = self.make_session()

        with self.assertRaisesRegex(RuntimeError, "outside configured limits"):
            session._move_axes({"x": 11.0})

        self.assertFalse(any(call[0] == "move" for call in self.motor.calls))

    def test_invalid_calibration_values_are_blockers(self):
        calibration = {
            **VALID_CALIBRATION,
            "turntable": {
                "center_mm": [0, 0, 0],
                "axis": [0, 0, 0],
                "mm_per_revolution": 0,
            },
        }
        session = self.make_session(calibration=calibration)

        readiness = session.readiness()

        self.assertFalse(readiness["ready"])
        self.assertTrue(any("Turntable axis" in item for item in readiness["blockers"]))
        self.assertTrue(any("mm_per_revolution" in item for item in readiness["blockers"]))

    def test_capture_timeout_forces_lasers_off_and_stops_motors(self):
        cameras = {
            "pi": _FakeCamera(block_after=1),
            "usb": _FakeCamera(),
        }
        config = {**SAFE_CONFIG, "capture_timeout_s": 0.03}
        session = self.make_session(cameras=cameras, config=config)

        session.start()
        status = self.wait_for_completion(session)

        self.assertEqual(status["phase"], "error")
        self.assertIn("timed out", status["error"])
        self.assertTrue(
            any("timed-out hardware operation" in item for item in status["preflight_blockers"])
        )
        self.assertFalse(any(self.gpio.state.values()))
        self.assertIn(("stop", "all"), self.motor.calls)

    def test_initial_motor_status_exception_is_contained_and_cleaned_up(self):
        session = self.make_session()
        get_status = self.motor.get_motor_status
        calls = 0

        def fail_first_acquisition_status():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError("motor status read failed")
            return get_status()

        self.motor.get_motor_status = fail_first_acquisition_status

        session.start()
        status = self.wait_for_completion(session)

        self.assertFalse(status["scanning"])
        self.assertEqual(status["phase"], "error")
        self.assertIn("motor status read failed", status["error"])
        self.assertFalse(any(self.gpio.state.values()))
        self.assertIn(("stop", "all"), self.motor.calls)

    def test_concurrent_start_is_rejected_while_preflight_is_reserved(self):
        lidar = _BlockingLidar()
        session = self.make_session(lidar=lidar)
        outcomes = []

        starter = threading.Thread(
            target=lambda: outcomes.append(session.start()),
            daemon=True,
        )
        starter.start()
        self.assertTrue(lidar.entered.wait(1))

        with self.assertRaisesRegex(RuntimeError, "already running"):
            session.start()

        lidar.release.set()
        starter.join(1)
        session.stop()

    def test_probed_preflight_does_not_touch_hardware_during_scan(self):
        cameras = {
            "pi": _FakeCamera(block_after=2),
            "usb": _FakeCamera(),
        }
        session = self.make_session(
            cameras=cameras,
            config={**SAFE_CONFIG, "stop_join_timeout_s": 0.01},
        )
        session.start()
        deadline = time.time() + 1
        while cameras["pi"].calls <= 2 and time.time() < deadline:
            time.sleep(0.005)
        calls_before = list(self.gpio.calls)

        readiness = session.readiness(probe=True)

        self.assertFalse(readiness["ready"])
        self.assertIn("Cannot probe hardware while a scan is active", readiness["blockers"])
        self.assertEqual(self.gpio.calls, calls_before)
        self.assertTrue(self.gpio.state["left"])
        session.stop()

    def test_physical_scan_reserves_shared_hardware_until_cleanup(self):
        reservation = threading.Lock()
        cameras = {
            "pi": _FakeCamera(block_after=2),
            "usb": _FakeCamera(),
        }
        session = self.make_session(
            cameras=cameras,
            config={**SAFE_CONFIG, "stop_join_timeout_s": 0.01},
        )
        session._hardware_reservation = reservation
        session.start()
        deadline = time.time() + 1
        while cameras["pi"].calls <= 2 and time.time() < deadline:
            time.sleep(0.005)

        self.assertTrue(session.hardware_reserved)
        self.assertFalse(reservation.acquire(blocking=False))

        session.stop()
        self.assertTrue(session.hardware_reserved)
        deadline = time.time() + 1
        while session.hardware_reserved and time.time() < deadline:
            time.sleep(0.01)
        self.assertFalse(session.hardware_reserved)
        self.assertTrue(reservation.acquire(blocking=False))
        reservation.release()

    def test_cancel_immediately_forces_lasers_off_and_stops_motors(self):
        cameras = {
            "pi": _FakeCamera(block_after=1),
            "usb": _FakeCamera(),
        }
        config = {**SAFE_CONFIG, "capture_timeout_s": 1.0}
        session = self.make_session(cameras=cameras, config=config)
        session.start()
        deadline = time.time() + 1
        while not self.gpio.state["left"] and time.time() < deadline:
            time.sleep(0.005)

        session.stop()

        self.assertFalse(any(self.gpio.state.values()))
        self.assertIn(("stop", "all"), self.motor.calls)
        self.assertIn(session.status()["phase"], {"cancelled", "cancelling"})

    @unittest.skipUnless(_CV2_AVAILABLE, "OpenCV required")
    def test_laser_difference_is_triangulated_with_calibrated_plane(self):
        import cv2

        session = self.make_session()
        ambient = np.zeros((8, 8, 3), dtype=np.uint8)
        laser = ambient.copy()
        laser[:, 2, 2] = 255
        ok_ambient, ambient_buffer = cv2.imencode(".jpg", ambient)
        ok_laser, laser_buffer = cv2.imencode(".jpg", laser)
        self.assertTrue(ok_ambient and ok_laser)

        points = ScanSession._extract_points(
            session,
            "pi",
            "left",
            ambient_buffer.tobytes(),
            laser_buffer.tobytes(),
            {"x": 0.0, "y": 0.0, "z": 0.0},
        )

        self.assertGreater(len(points), 0)
        self.assertTrue(all(abs(point[2] - 100.0) < 1e-6 for point in points))


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
        entered = threading.Event()
        release = threading.Event()

        def blocking_poisson(_pcd, depth):
            entered.set()
            release.wait(1)
            return _FakeMesh(), [1.0, 1.0, 1.0]

        with (
            mock.patch("software.api.scanner_engine._O3D_AVAILABLE", True),
            mock.patch("software.api.scanner_engine.o3d", _FakeO3D(), create=True),
            mock.patch.object(
                _FakeTriangleMesh,
                "create_from_point_cloud_poisson",
                side_effect=blocking_poisson,
            ),
        ):
            first = engine.reconstruct()
            self.assertTrue(entered.wait(1))
            second = engine.reconstruct()
            release.set()
            # Drain the background thread before finishing the test.
            deadline = time.time() + 5
            while engine.status()["in_progress"] and time.time() < deadline:
                time.sleep(0.01)

        self.assertTrue(first["in_progress"])
        self.assertTrue(second["in_progress"])
        self.assertFalse(second.get("started", True))


if __name__ == "__main__":
    unittest.main()
