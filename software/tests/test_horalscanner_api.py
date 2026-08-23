"""
Tests for horalscanner_api.py endpoints.
Uses Flask test client so no real hardware is required.
"""

import unittest
import sys
from pathlib import Path

# Make software.app importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestHoralScannerAPI(unittest.TestCase):
    """Integration tests for the Flask REST API."""

    def setUp(self):
        # Import here so module-level hardware init uses stubs already in place
        import software.api.horalscanner_api as api_module

        # Reset shared state between tests
        api_module._state.update(
            {
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "lasers": {"left": False, "right": False},
                "led": {"r": 0, "g": 0, "b": 0},
                "fans": {"fan1": False, "fan2": False},
                "scan_active": False,
                "scan_progress": 0,
                "last_lidar_mm": None,
                "temperature": None,
            }
        )
        self.client = api_module.app.test_client()

    # ------------------------------------------------------------------
    # Health / status
    # ------------------------------------------------------------------

    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "ok"})

    def test_status_returns_limits(self):
        resp = self.client.get("/api/status")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("limits", data)
        self.assertEqual(data["limits"]["x_max_mm"], 210.0)
        self.assertEqual(data["limits"]["y_max_mm"], 628.32)
        self.assertEqual(data["limits"]["z_max_mm"], 270.0)

    def test_status_contains_position(self):
        resp = self.client.get("/api/status")
        data = resp.get_json()
        self.assertIn("position", data)
        self.assertIn("x", data["position"])

    # ------------------------------------------------------------------
    # Axis movement
    # ------------------------------------------------------------------

    def test_move_x(self):
        resp = self.client.post("/api/move/x", json={"mm": 100.0})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["mm"], 100.0)
        self.assertEqual(data["axis"], "x")

    def test_move_x_clamped(self):
        """Values above X_MAX_MM should be clamped to 210."""
        resp = self.client.post("/api/move/x", json={"mm": 999.0})
        self.assertEqual(resp.get_json()["mm"], 210.0)

    def test_move_y(self):
        resp = self.client.post("/api/move/y", json={"mm": 300.0})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["mm"], 300.0)

    def test_move_z(self):
        resp = self.client.post("/api/move/z", json={"mm": 50.0})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["mm"], 50.0)

    def test_move_multi_axis(self):
        resp = self.client.post("/api/move", json={"x": 10.0, "y": 20.0, "z": 30.0})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["position"]["x"], 10.0)
        self.assertEqual(data["position"]["y"], 20.0)
        self.assertEqual(data["position"]["z"], 30.0)

    def test_home(self):
        resp = self.client.post("/api/home")
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["position"]["x"], 0.0)

    # ------------------------------------------------------------------
    # Laser control
    # ------------------------------------------------------------------

    def test_laser_set(self):
        resp = self.client.post("/api/laser", json={"left": True, "right": False})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data["lasers"]["left"])
        self.assertFalse(data["lasers"]["right"])

    def test_laser_left_endpoint(self):
        resp = self.client.post("/api/laser/left", json={"on": True})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["lasers"]["left"])

    def test_laser_right_endpoint(self):
        resp = self.client.post("/api/laser/right", json={"on": True})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["lasers"]["right"])

    # ------------------------------------------------------------------
    # Camera / LIDAR
    # ------------------------------------------------------------------

    def test_camera_capture(self):
        resp = self.client.post("/api/camera/capture")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("lidar_distance_mm", data)
        self.assertIn("usb_camera_available", data)

    def test_lidar_read(self):
        resp = self.client.get("/api/lidar")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("lidar_distance_mm", resp.get_json())

    # ------------------------------------------------------------------
    # LED RGB
    # ------------------------------------------------------------------

    def test_led_set(self):
        resp = self.client.post("/api/led", json={"r": 255, "g": 128, "b": 0})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["led"]["r"], 255)
        self.assertEqual(data["led"]["g"], 128)
        self.assertEqual(data["led"]["b"], 0)

    def test_led_clamped(self):
        resp = self.client.post("/api/led", json={"r": 999, "g": -5, "b": 50})
        data = resp.get_json()
        self.assertEqual(data["led"]["r"], 255)
        self.assertEqual(data["led"]["g"], 0)

    def test_led_off(self):
        # First turn on, then off
        self.client.post("/api/led", json={"r": 200, "g": 200, "b": 200})
        resp = self.client.post("/api/led/off")
        data = resp.get_json()
        self.assertEqual(data["led"]["r"], 0)
        self.assertEqual(data["led"]["g"], 0)
        self.assertEqual(data["led"]["b"], 0)

    # ------------------------------------------------------------------
    # Fans / temperature
    # ------------------------------------------------------------------

    def test_fan_control(self):
        resp = self.client.post("/api/fan", json={"fan1": True})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data["fans"]["fan1"])

    def test_temperature(self):
        resp = self.client.get("/api/temperature")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("temperature_c", resp.get_json())

    # ------------------------------------------------------------------
    # Scan acquisition
    # ------------------------------------------------------------------

    def test_scan_step(self):
        resp = self.client.post("/api/scan/step", json={"x_mm": 10.0, "sync_token": "t1"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["x_mm"], 10.0)

    def test_scan_start_stop(self):
        resp = self.client.post("/api/scan/start")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "started")

        resp2 = self.client.post("/api/scan/stop")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.get_json()["status"], "stopped")

    def test_scan_start_conflict(self):
        self.client.post("/api/scan/start")
        resp = self.client.post("/api/scan/start")
        self.assertEqual(resp.status_code, 409)

    def test_scan_progress(self):
        resp = self.client.get("/api/scan/progress")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("scan_active", data)
        self.assertIn("scan_progress", data)


if __name__ == "__main__":
    unittest.main()
