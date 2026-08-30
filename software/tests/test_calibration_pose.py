"""Tests for camera calibration pose API endpoints and PoseMemory."""

import importlib
import json
import os
import tempfile
import unittest


class TestPoseMemory(unittest.TestCase):
    """Unit tests for PoseMemory persistence."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)  # start without file

        from software.api.calibration_pose import PoseMemory
        self.memory = PoseMemory(path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_get_pose_returns_none_when_empty(self):
        self.assertIsNone(self.memory.get_pose("pi"))

    def test_save_and_get_pose(self):
        self.memory.save_pose("pi", {"x": 100.0, "y": 5.0})
        pose = self.memory.get_pose("pi")
        self.assertIsNotNone(pose)
        self.assertAlmostEqual(pose["x"], 100.0)
        self.assertAlmostEqual(pose["y"], 5.0)

    def test_save_persists_to_disk(self):
        self.memory.save_pose("usb", {"x": 98.0, "y": 2.0, "z": 150.0})
        with open(self.tmp.name) as fh:
            data = json.load(fh)
        self.assertIn("usb", data)
        self.assertAlmostEqual(data["usb"]["z"], 150.0)

    def test_reload_restores_poses(self):
        self.memory.save_pose("pi", {"x": 50.0, "y": 10.0})

        from software.api.calibration_pose import PoseMemory
        reloaded = PoseMemory(path=self.tmp.name)
        pose = reloaded.get_pose("pi")
        self.assertAlmostEqual(pose["x"], 50.0)

    def test_all_poses_returns_all_cameras(self):
        self.memory.save_pose("pi", {"x": 1.0, "y": 2.0})
        self.memory.save_pose("usb", {"x": 3.0, "y": 4.0, "z": 5.0})
        all_poses = self.memory.all_poses()
        self.assertIn("pi", all_poses)
        self.assertIn("usb", all_poses)


class TestGetDefaultPose(unittest.TestCase):
    def setUp(self):
        from software.api.calibration_pose import get_default_pose
        self.get_default_pose = get_default_pose

    def test_pi_pose_has_no_z(self):
        pose = self.get_default_pose("pi")
        self.assertIsNotNone(pose)
        self.assertIn("x", pose)
        self.assertIn("y", pose)
        self.assertNotIn("z", pose)

    def test_usb_pose_has_z(self):
        pose = self.get_default_pose("usb")
        self.assertIsNotNone(pose)
        self.assertIn("x", pose)
        self.assertIn("y", pose)
        self.assertIn("z", pose)

    def test_unknown_camera_returns_none(self):
        self.assertIsNone(self.get_default_pose("unknown"))


class TestMoveToPose(unittest.TestCase):
    def setUp(self):
        from software.api.calibration_pose import move_to_pose
        self.move_to_pose = move_to_pose

    def _make_driver(self, positions=None):
        class FakeSTM32:
            def __init__(self, pos):
                self.calls = []
                self._positions = pos or {"x": 0.0, "y": 0.0, "z": 0.0}

            def get_motor_status(self):
                return {"positions": dict(self._positions)}

            def move_motor(self, axis, distance):
                self.calls.append((axis, distance))
                self._positions[axis] = self._positions.get(axis, 0.0) + distance
                return True

        return FakeSTM32(positions)

    def test_moves_xy_for_pi_pose(self):
        driver = self._make_driver()
        moved = self.move_to_pose(driver, {"x": 100.0, "y": 5.0})
        axes_moved = {call[0] for call in driver.calls}
        self.assertIn("x", axes_moved)
        self.assertIn("y", axes_moved)
        self.assertNotIn("z", axes_moved)
        self.assertIn("x", moved)
        self.assertIn("y", moved)

    def test_moves_xyz_for_usb_pose(self):
        driver = self._make_driver()
        moved = self.move_to_pose(driver, {"x": 100.0, "y": 0.0, "z": 150.0})
        axes_moved = {call[0] for call in driver.calls}
        self.assertIn("z", axes_moved)
        self.assertIn("z", moved)

    def test_skips_axis_already_at_target(self):
        driver = self._make_driver({"x": 100.0, "y": 0.0, "z": 0.0})
        self.move_to_pose(driver, {"x": 100.0, "y": 0.0})
        # x and y are already at target, no moves should be issued
        self.assertEqual(len(driver.calls), 0)

    def test_raises_connection_error_when_driver_none(self):
        with self.assertRaises(ConnectionError):
            self.move_to_pose(None, {"x": 10.0})

    def test_raises_runtime_error_on_move_failure(self):
        class FailDriver:
            def get_motor_status(self):
                return {"positions": {"x": 0.0, "y": 0.0}}

            def move_motor(self, axis, distance):
                return False

        with self.assertRaises(RuntimeError):
            self.move_to_pose(FailDriver(), {"x": 50.0})


try:
    from flask import Flask  # noqa: F401
    _FLASK_AVAILABLE = True
except Exception:
    _FLASK_AVAILABLE = False


@unittest.skipIf(not _FLASK_AVAILABLE, "Flask required")
class TestCalibrationPoseAPIEndpoints(unittest.TestCase):
    """Integration tests for the calibration pose API endpoints."""

    def setUp(self):
        self.api_module = importlib.import_module("software.api.horalscanner_api")

        class FakeSTM32:
            def __init__(self):
                self.calls = []
                self._positions = {"x": 0.0, "y": 0.0, "z": 0.0}
                self.status = {
                    "positions": self._positions,
                    "moving": {"x": False, "y": False, "z": False},
                    "temperature_c": 0.0,
                }

            def move_motor(self, axis, distance):
                self.calls.append(("move_motor", axis, distance))
                self._positions[axis] = self._positions.get(axis, 0.0) + distance
                self.status["positions"] = dict(self._positions)
                return True

            def home_motor(self, axis):
                return True

            def stop_motor(self, axis="all"):
                return True

            def get_motor_status(self):
                return {
                    "positions": dict(self._positions),
                    "moving": {"x": False, "y": False, "z": False},
                }

        self.fake_stm32 = FakeSTM32()
        self.api_module.stm32_driver = self.fake_stm32

        # Use an isolated temporary PoseMemory
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        from software.api.calibration_pose import PoseMemory
        self.api_module.pose_memory = PoseMemory(path=self.tmp.name)
        self.original_lidar_driver = self.api_module.lidar_driver

        self.client = self.api_module.app.test_client()

    def tearDown(self):
        self.api_module.lidar_driver = self.original_lidar_driver
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    # ------------------------------------------------------------------
    # goto_calibration_pose
    # ------------------------------------------------------------------

    def test_goto_pi_calibration_pose_returns_200(self):
        r = self.client.post("/api/camera/pi/goto_calibration_pose")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["camera"], "pi")

    def test_goto_pi_calibration_pose_does_not_move_z(self):
        self.client.post("/api/camera/pi/goto_calibration_pose")
        axes_moved = {call[1] for call in self.fake_stm32.calls if call[0] == "move_motor"}
        self.assertNotIn("z", axes_moved)

    def test_goto_usb_calibration_pose_moves_z(self):
        self.client.post("/api/camera/usb/goto_calibration_pose")
        axes_moved = {call[1] for call in self.fake_stm32.calls if call[0] == "move_motor"}
        self.assertIn("z", axes_moved)

    def test_goto_calibration_pose_unknown_camera_returns_404(self):
        r = self.client.post("/api/camera/webcam/goto_calibration_pose")
        self.assertEqual(r.status_code, 404)

    def test_goto_calibration_pose_no_driver_returns_503(self):
        self.api_module.stm32_driver = None
        r = self.client.post("/api/camera/pi/goto_calibration_pose")
        self.assertEqual(r.status_code, 503)
        self.api_module.stm32_driver = self.fake_stm32

    # ------------------------------------------------------------------
    # save_scan_pose
    # ------------------------------------------------------------------

    def test_save_scan_pose_pi_returns_200(self):
        r = self.client.post("/api/camera/pi/save_scan_pose")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertIn("saved_pose", data)

    def test_save_scan_pose_pi_excludes_z(self):
        r = self.client.post("/api/camera/pi/save_scan_pose")
        saved = r.get_json()["saved_pose"]
        self.assertNotIn("z", saved)

    def test_save_scan_pose_usb_includes_z(self):
        self.fake_stm32._positions["z"] = 150.0
        self.fake_stm32.status["positions"]["z"] = 150.0
        r = self.client.post("/api/camera/usb/save_scan_pose")
        saved = r.get_json()["saved_pose"]
        self.assertIn("z", saved)

    # ------------------------------------------------------------------
    # goto_scan_pose
    # ------------------------------------------------------------------

    def test_goto_scan_pose_404_when_not_saved(self):
        r = self.client.post("/api/camera/pi/goto_scan_pose")
        self.assertEqual(r.status_code, 404)

    def test_goto_scan_pose_restores_saved_pose(self):
        # Save a pose first
        self.client.post("/api/camera/pi/save_scan_pose")
        self.fake_stm32.calls.clear()
        # Move away
        self.fake_stm32._positions["x"] = 50.0
        # Restore
        r = self.client.post("/api/camera/pi/goto_scan_pose")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])

    def test_scan_pose_memory_is_isolated_per_camera(self):
        self.fake_stm32._positions.update({"x": 10.0, "y": 20.0, "z": 30.0})
        self.client.post("/api/camera/pi/save_scan_pose")
        self.fake_stm32._positions.update({"x": 100.0, "y": 200.0, "z": 300.0})
        self.client.post("/api/camera/usb/save_scan_pose")
        poses = self.client.get("/api/camera/scan_poses").get_json()["poses"]
        self.assertEqual(poses["pi"], {"x": 10.0, "y": 20.0})
        self.assertEqual(poses["usb"], {"x": 100.0, "y": 200.0, "z": 300.0})

    def test_goto_calibration_pose_with_lidar_connected_returns_distance(self):
        class FakeLidar:
            connected = True

            def read_distance_mm(self):
                return 300.0

        self.api_module.lidar_driver = FakeLidar()
        r = self.client.post("/api/camera/pi/goto_calibration_pose")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["lidar_distance_mm"], 300.0)

    def test_goto_calibration_pose_with_lidar_disconnected_returns_null_distance(self):
        class FakeLidar:
            connected = False

            def connect(self):
                return False

        self.api_module.lidar_driver = FakeLidar()
        r = self.client.post("/api/camera/pi/goto_calibration_pose")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.get_json()["lidar_distance_mm"])

    # ------------------------------------------------------------------
    # scan_poses GET
    # ------------------------------------------------------------------

    def test_scan_poses_returns_dict(self):
        r = self.client.get("/api/camera/scan_poses")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("poses", data)
        self.assertIsInstance(data["poses"], dict)


if __name__ == "__main__":
    unittest.main()
