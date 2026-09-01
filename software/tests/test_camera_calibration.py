"""Tests for camera calibration pose endpoints and the camera_calibration module."""

from __future__ import annotations

import importlib
import unittest


class CameraCalibrationModuleTests(unittest.TestCase):
    """Unit tests for software.api.camera_calibration."""

    def setUp(self):
        self.mod = importlib.import_module("software.api.camera_calibration")

    # ------------------------------------------------------------------
    # Pose definitions
    # ------------------------------------------------------------------

    def test_pi_camera_pose_has_no_z(self):
        pose = self.mod.get_calibration_pose("pi")
        self.assertIsNotNone(pose)
        self.assertIsNone(pose["z"], "Pi Camera pose must not specify Z")

    def test_logitech_pose_has_xyz(self):
        pose = self.mod.get_calibration_pose("usb")
        self.assertIsNotNone(pose)
        self.assertIsNotNone(pose["z"], "Logitech pose must specify Z")
        self.assertIsNotNone(pose["x"])
        self.assertIsNotNone(pose["y"])

    def test_unknown_camera_returns_none(self):
        self.assertIsNone(self.mod.get_calibration_pose("unknown"))

    # ------------------------------------------------------------------
    # move_to_calibration_pose
    # ------------------------------------------------------------------

    def _make_fake_stm32(self):
        class FakeSTM32:
            def __init__(self):
                self.calls = []
                self.status = {"positions": {"x": 5.0, "y": 10.0, "z": 20.0}}

            def move_motor(self, axis, distance):
                self.calls.append((axis, distance))

            def get_motor_status(self):
                return dict(self.status)

        return FakeSTM32()

    def test_pi_camera_moves_only_xy(self):
        stm32 = self._make_fake_stm32()
        result = self.mod.move_to_calibration_pose("pi", stm32)
        self.assertTrue(result["ok"])
        axes = {call[0] for call in stm32.calls}
        self.assertIn("x", axes)
        self.assertIn("y", axes)
        self.assertNotIn("z", axes, "Pi Camera must NOT move Z")

    def test_logitech_moves_xyz(self):
        stm32 = self._make_fake_stm32()
        result = self.mod.move_to_calibration_pose("usb", stm32)
        self.assertTrue(result["ok"])
        axes = {call[0] for call in stm32.calls}
        self.assertIn("x", axes)
        self.assertIn("y", axes)
        self.assertIn("z", axes)

    def test_move_returns_ok_false_for_unknown_camera(self):
        stm32 = self._make_fake_stm32()
        result = self.mod.move_to_calibration_pose("unknown", stm32)
        self.assertFalse(result["ok"])

    def test_move_returns_ok_false_when_no_driver(self):
        result = self.mod.move_to_calibration_pose("pi", None)
        self.assertFalse(result["ok"])

    # ------------------------------------------------------------------
    # Pose memory: save / restore
    # ------------------------------------------------------------------

    def test_save_and_restore_current_pose(self):
        # Reset in-memory poses
        self.mod._scan_poses.clear()
        stm32 = self._make_fake_stm32()
        stm32.status = {"positions": {"x": 3.0, "y": 7.0, "z": 15.0}}

        save_result = self.mod.save_current_pose("pi", stm32)
        self.assertTrue(save_result["ok"])
        self.assertEqual(save_result["pose"]["x"], 3.0)
        self.assertEqual(save_result["pose"]["y"], 7.0)

        saved = self.mod.get_saved_pose("pi")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["x"], 3.0)

    def test_restore_saved_pose_moves_motors(self):
        self.mod._scan_poses["usb"] = {"x": 1.0, "y": 2.0, "z": 30.0}
        stm32 = self._make_fake_stm32()
        result = self.mod.restore_scan_pose("usb", stm32)
        self.assertTrue(result["ok"])
        self.assertIn("X", result["axes_moved"])
        self.assertIn("Z", result["axes_moved"])

    def test_restore_nonexistent_pose_returns_error(self):
        self.mod._scan_poses.pop("pi", None)
        stm32 = self._make_fake_stm32()
        result = self.mod.restore_scan_pose("pi", stm32)
        self.assertFalse(result["ok"])

    def test_save_pose_no_driver_returns_error(self):
        result = self.mod.save_current_pose("pi", None)
        self.assertFalse(result["ok"])

    # ------------------------------------------------------------------
    # TF-Luna integration
    # ------------------------------------------------------------------

    def test_lidar_distance_returned_when_available(self):
        class FakeLidar:
            connected = True

            def read_distance_mm(self):
                return 320.0

        stm32 = self._make_fake_stm32()
        result = self.mod.move_to_calibration_pose("pi", stm32, lidar_driver=FakeLidar())
        self.assertTrue(result["ok"])
        self.assertEqual(result["lidar_distance_mm"], 320.0)

    def test_lidar_none_when_read_fails(self):
        class BrokenLidar:
            connected = True

            def read_distance_mm(self):
                raise RuntimeError("read error")

        stm32 = self._make_fake_stm32()
        result = self.mod.move_to_calibration_pose("pi", stm32, lidar_driver=BrokenLidar())
        self.assertTrue(result["ok"])
        self.assertIsNone(result["lidar_distance_mm"])


try:
    from flask import Flask  # noqa: F401
    _FLASK_AVAILABLE = True
except Exception:
    _FLASK_AVAILABLE = False


@unittest.skipIf(not _FLASK_AVAILABLE, "Flask is required for API tests")
class CameraCalibrationAPITests(unittest.TestCase):
    """Integration tests for the calibration pose API endpoints."""

    def setUp(self):
        from api import create_app

        self.api_module = importlib.import_module("api.horalscanner_api")
        self.calib_module = importlib.import_module("software.api.camera_calibration")
        self.app = create_app()

        class FakeSTM32:
            def __init__(self):
                self.calls = []
                self.status = {"positions": {"x": 0.0, "y": 0.0, "z": 0.0}}

            def move_motor(self, axis, distance):
                self.calls.append(("move_motor", axis, distance))

            def get_motor_status(self):
                return dict(self.status)

        self.fake_stm32 = FakeSTM32()
        self.original_stm32 = self.api_module.stm32_driver
        self.api_module.stm32_driver = self.fake_stm32
        self.addCleanup(setattr, self.api_module, "stm32_driver", self.original_stm32)

        # Patch lidar to be disconnected so we don't need hardware
        self.original_lidar = self.api_module.lidar_driver

        class FakeLidar:
            connected = False

        self.api_module.lidar_driver = FakeLidar()
        self.addCleanup(setattr, self.api_module, "lidar_driver", self.original_lidar)

        self.client = self.app.test_client()

    # ------------------------------------------------------------------

    def test_pose_pi_moves_only_xy(self):
        response = self.client.post("/api/camera/calibrate/pose/pi")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        axes = data["axes_moved"]
        self.assertIn("X", axes)
        self.assertIn("Y", axes)
        self.assertNotIn("Z", axes)

    def test_pose_usb_moves_xyz(self):
        response = self.client.post("/api/camera/calibrate/pose/usb")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        axes = data["axes_moved"]
        self.assertIn("X", axes)
        self.assertIn("Y", axes)
        self.assertIn("Z", axes)

    def test_pose_invalid_camera_returns_400(self):
        response = self.client.post("/api/camera/calibrate/pose/invalid")
        self.assertEqual(response.status_code, 400)

    def test_pose_no_stm32_returns_503(self):
        self.api_module.stm32_driver = None
        response = self.client.post("/api/camera/calibrate/pose/pi")
        self.assertEqual(response.status_code, 503)

    def test_save_pose_stores_current_position(self):
        self.fake_stm32.status = {"positions": {"x": 5.0, "y": 3.0, "z": 12.0}}
        response = self.client.post("/api/scan/pose/save", json={"camera": "pi"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["pose"]["x"], 5.0)

    def test_restore_pose_moves_motors(self):
        self.calib_module._scan_poses["usb"] = {"x": 1.0, "y": 2.0, "z": 30.0}
        response = self.client.post("/api/scan/pose/restore", json={"camera": "usb"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("X", data["axes_moved"])

    def test_restore_nonexistent_pose_returns_404(self):
        self.calib_module._scan_poses.pop("pi", None)
        response = self.client.post("/api/scan/pose/restore", json={"camera": "pi"})
        self.assertEqual(response.status_code, 404)

    def test_get_poses_returns_dict(self):
        response = self.client.get("/api/scan/pose")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("poses", data)

    def test_save_pose_invalid_camera_returns_400(self):
        response = self.client.post("/api/scan/pose/save", json={"camera": "badcam"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
