"""Tests for camera calibration pose selection, X/Y/Z rules, pose memorization
and the API endpoints added in camera_calibration.py / horalscanner_api.py."""

from __future__ import annotations

import importlib
import unittest


# ---------------------------------------------------------------------------
# Unit tests for the camera_calibration module
# ---------------------------------------------------------------------------


class TestGetCalibrationPose(unittest.TestCase):
    """Pose definitions and camera-specific axis rules."""

    def setUp(self):
        self.mod = importlib.import_module("software.api.camera_calibration")
        # Reset saved poses between tests
        self.mod._saved_poses.clear()

    def test_pi_pose_has_x_and_y_only(self):
        pose = self.mod.get_calibration_pose("pi")
        self.assertIn("x", pose)
        self.assertIn("y", pose)
        self.assertNotIn("z", pose, "Pi Camera pose must not include Z")

    def test_usb_pose_has_x_y_and_z(self):
        pose = self.mod.get_calibration_pose("usb")
        self.assertIn("x", pose)
        self.assertIn("y", pose)
        self.assertIn("z", pose, "Logitech USB pose must include Z")

    def test_unknown_camera_raises(self):
        with self.assertRaises(ValueError):
            self.mod.get_calibration_pose("webcam")

    def test_returns_copy(self):
        pose1 = self.mod.get_calibration_pose("pi")
        pose1["x"] = 999.0
        pose2 = self.mod.get_calibration_pose("pi")
        self.assertNotEqual(pose2["x"], 999.0)


class TestSaveScanPose(unittest.TestCase):
    """Scan-pose memorization."""

    def setUp(self):
        self.mod = importlib.import_module("software.api.camera_calibration")
        self.mod._saved_poses.clear()

    def test_save_and_retrieve_pi_pose(self):
        positions = {"x": 10.0, "y": 5.0, "z": 0.0}
        saved = self.mod.save_scan_pose("pi", positions)
        retrieved = self.mod.get_saved_scan_pose("pi")
        self.assertEqual(saved, retrieved)

    def test_save_and_retrieve_usb_pose(self):
        positions = {"x": 15.0, "y": 7.0, "z": 50.0}
        self.mod.save_scan_pose("usb", positions)
        retrieved = self.mod.get_saved_scan_pose("usb")
        self.assertEqual(retrieved["z"], 50.0)

    def test_no_saved_pose_returns_none(self):
        result = self.mod.get_saved_scan_pose("pi")
        self.assertIsNone(result)

    def test_clear_saved_pose(self):
        self.mod.save_scan_pose("pi", {"x": 1.0, "y": 2.0})
        self.mod.clear_saved_pose("pi")
        self.assertIsNone(self.mod.get_saved_scan_pose("pi"))

    def test_poses_are_camera_specific(self):
        self.mod.save_scan_pose("pi", {"x": 1.0, "y": 2.0})
        self.assertIsNone(self.mod.get_saved_scan_pose("usb"))


class TestMoveToPose(unittest.TestCase):
    """move_to_pose motor movement logic."""

    def setUp(self):
        self.mod = importlib.import_module("software.api.camera_calibration")
        self.mod._saved_poses.clear()

    def _fake_stm32(self, positions=None):
        class FakeSTM32:
            def __init__(self):
                self.calls = []
                self._positions = positions or {"x": 0.0, "y": 0.0, "z": 0.0}

            def get_motor_status(self):
                return {"positions": dict(self._positions)}

            def move_motor(self, axis, delta):
                self.calls.append((axis, delta))
                self._positions[axis.lower()] += delta
                return True

        return FakeSTM32()

    def test_pi_does_not_move_z(self):
        stm32 = self._fake_stm32({"x": 5.0, "y": 3.0, "z": 20.0})
        self.mod.move_to_pose(stm32, "pi")
        moved_axes = {call[0] for call in stm32.calls}
        self.assertNotIn("Z", moved_axes, "Pi Camera must not move Z axis")

    def test_usb_can_move_z(self):
        stm32 = self._fake_stm32({"x": 5.0, "y": 3.0, "z": 0.0})
        self.mod.move_to_pose(stm32, "usb")
        moved_axes = {call[0] for call in stm32.calls}
        self.assertIn("Z", moved_axes, "Logitech USB must move Z axis")

    def test_no_move_when_already_at_pose(self):
        pose = self.mod.get_calibration_pose("pi")
        stm32 = self._fake_stm32({"x": pose["x"], "y": pose["y"], "z": 0.0})
        result = self.mod.move_to_pose(stm32, "pi")
        self.assertEqual(result["moves_done"], [])

    def test_result_contains_expected_keys(self):
        stm32 = self._fake_stm32()
        result = self.mod.move_to_pose(stm32, "pi")
        for key in ("camera", "pose", "moves_done", "lidar_distance_mm", "lidar_ok"):
            self.assertIn(key, result)

    def test_move_to_pose_with_disconnected_lidar(self):
        stm32 = self._fake_stm32()

        class FakeLidar:
            connected = False

        result = self.mod.move_to_pose(stm32, "pi", lidar_driver=FakeLidar())
        self.assertIsNone(result["lidar_distance_mm"])

    def test_move_to_pose_with_connected_lidar(self):
        stm32 = self._fake_stm32()

        class FakeLidar:
            connected = True

            def read_distance_mm(self):
                return 300.0

        result = self.mod.move_to_pose(stm32, "pi", lidar_driver=FakeLidar())
        self.assertEqual(result["lidar_distance_mm"], 300.0)


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


try:
    from flask import Flask  # noqa: F401
    _FLASK_AVAILABLE = True
except Exception:  # pragma: no cover
    _FLASK_AVAILABLE = False


@unittest.skipIf(not _FLASK_AVAILABLE, "Flask is required for API tests")
class TestCalibrationPoseAPI(unittest.TestCase):

    def setUp(self):
        self.api_module = importlib.import_module("software.api.horalscanner_api")
        self.cal_module = importlib.import_module("software.api.camera_calibration")
        self.cal_module._saved_poses.clear()

        class FakeSTM32:
            def __init__(self):
                self.calls = []
                self._positions = {"x": 0.0, "y": 0.0, "z": 0.0}

            def move_motor(self, axis, delta):
                self.calls.append(("move_motor", axis, delta))
                self._positions[axis.lower()] += delta
                return True

            def get_motor_status(self):
                return {"positions": dict(self._positions)}

            def home_motor(self, axis):
                return True

            def stop_motor(self, axis="all"):
                return True

        self.fake_stm32 = FakeSTM32()
        self.api_module.stm32_driver = self.fake_stm32
        self.client = self.api_module.app.test_client()

    # -- /api/calibration/pose/<camera> GET --

    def test_pose_info_pi(self):
        resp = self.client.get("/api/calibration/pose/pi")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertNotIn("z", data["default_pose"])

    def test_pose_info_usb(self):
        resp = self.client.get("/api/calibration/pose/usb")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("z", data["default_pose"])

    def test_pose_info_unknown_camera(self):
        resp = self.client.get("/api/calibration/pose/gopro")
        self.assertEqual(resp.status_code, 400)

    # -- /api/calibration/pose/<camera> POST --

    def test_move_to_pi_pose(self):
        resp = self.client.post("/api/calibration/pose/pi")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["camera"], "pi")
        self.assertNotIn("z", data["pose"])

    def test_move_to_usb_pose(self):
        resp = self.client.post("/api/calibration/pose/usb")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("z", data["pose"])

    def test_move_to_pose_unknown_camera(self):
        resp = self.client.post("/api/calibration/pose/gopro")
        self.assertEqual(resp.status_code, 400)

    def test_pi_move_does_not_touch_z(self):
        self.fake_stm32._positions = {"x": 5.0, "y": 3.0, "z": 20.0}
        self.client.post("/api/calibration/pose/pi")
        moved_axes = {call[1] for call in self.fake_stm32.calls if call[0] == "move_motor"}
        self.assertNotIn("Z", moved_axes)

    def test_usb_move_includes_z(self):
        self.fake_stm32._positions = {"x": 5.0, "y": 3.0, "z": 0.0}
        self.client.post("/api/calibration/pose/usb")
        moved_axes = {call[1] for call in self.fake_stm32.calls if call[0] == "move_motor"}
        self.assertIn("Z", moved_axes)

    # -- /api/calibration/pose/<camera>/save POST --

    def test_save_pose_pi(self):
        resp = self.client.post("/api/calibration/pose/pi/save")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["camera"], "pi")
        self.assertIn("saved_pose", data)

    def test_save_pose_usb(self):
        resp = self.client.post("/api/calibration/pose/usb/save")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

    # -- /api/calibration/pose/<camera>/restore POST --

    def test_restore_pose_not_saved_returns_404(self):
        resp = self.client.post("/api/calibration/pose/pi/restore")
        self.assertEqual(resp.status_code, 404)

    def test_restore_pose_after_save(self):
        # Save a pose first
        self.cal_module.save_scan_pose("pi", {"x": 10.0, "y": 5.0})
        # Move elsewhere
        self.fake_stm32._positions = {"x": 50.0, "y": 50.0, "z": 0.0}
        resp = self.client.post("/api/calibration/pose/pi/restore")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("restored_pose", data)

    def test_restore_pose_usb_no_z_if_not_saved(self):
        self.cal_module.save_scan_pose("usb", {"x": 0.0, "y": 0.0, "z": 50.0})
        resp = self.client.post("/api/calibration/pose/usb/restore")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
