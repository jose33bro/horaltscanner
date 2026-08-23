"""
Tests for HoralScanner API modules (klipper_client, scanner_engine, slicer_bridge, lidar_driver).
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure software/api is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

# Stub heavy optional dependencies before importing modules
for _stub in ("open3d", "picamera2", "gpiozero", "RPi", "RPi.GPIO"):
    if _stub not in sys.modules:
        sys.modules[_stub] = types.ModuleType(_stub)


class TestScannerEngine(unittest.TestCase):
    def setUp(self):
        from scanner_engine import ScannerEngine, PointCloudBuffer
        self.ScannerEngine = ScannerEngine
        self.PointCloudBuffer = PointCloudBuffer

    def test_point_cloud_buffer_add_and_count(self):
        buf = self.PointCloudBuffer()
        buf.add_point(1.0, 2.0, 3.0)
        buf.add_point(4.0, 5.0, 6.0)
        self.assertEqual(buf.count(), 2)

    def test_point_cloud_buffer_reset(self):
        buf = self.PointCloudBuffer()
        buf.add_point(0.0, 0.0, 0.0)
        buf.reset()
        self.assertEqual(buf.count(), 0)

    def test_point_cloud_buffer_to_dict(self):
        buf = self.PointCloudBuffer()
        buf.add_point(1.0, 2.0, 3.0, 1.0, 0.0, 0.0)
        d = buf.to_dict()
        self.assertIn("points", d)
        self.assertIn("colors", d)
        self.assertEqual(d["count"], 1)

    def test_scanner_engine_start_stop(self):
        engine = self.ScannerEngine()
        engine.start()
        self.assertTrue(engine.scanning)
        engine.stop()
        self.assertFalse(engine.scanning)

    def test_scanner_engine_status(self):
        engine = self.ScannerEngine()
        engine.start()
        s = engine.status()
        self.assertIn("scanning", s)
        self.assertIn("points", s)
        self.assertIn("elapsed_s", s)
        engine.stop()

    def test_reconstruct_returns_none_without_open3d(self):
        import scanner_engine as se
        orig = se.OPEN3D_AVAILABLE
        se.OPEN3D_AVAILABLE = False
        engine = self.ScannerEngine()
        result = engine.reconstruct_mesh()
        self.assertIsNone(result)
        se.OPEN3D_AVAILABLE = orig


class TestKlipperClient(unittest.TestCase):
    def setUp(self):
        from klipper_client import KlipperClient
        self.KlipperClient = KlipperClient

    @patch("klipper_client.serial.Serial")
    def test_connect_success(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_serial_cls.return_value = mock_ser
        mock_ser.is_open = True
        client = self.KlipperClient(port="/dev/ttyFAKE", baud=115200)
        with patch("klipper_client.time.sleep"):
            ok = client.connect()
        self.assertTrue(ok)
        self.assertTrue(client.connected)

    @patch("klipper_client.serial.Serial", side_effect=Exception("no port"))
    def test_connect_failure(self, _):
        client = self.KlipperClient(port="/dev/null", baud=115200)
        ok = client.connect()
        self.assertFalse(ok)
        self.assertFalse(client.connected)

    def test_send_gcode_not_connected_raises(self):
        client = self.KlipperClient()
        with self.assertRaises(ConnectionError):
            client.send_gcode("G28")


class TestMoonrakerClient(unittest.TestCase):
    def setUp(self):
        from klipper_client import MoonrakerClient
        self.MoonrakerClient = MoonrakerClient

    def test_test_connection_failure_no_server(self):
        client = self.MoonrakerClient(base_url="http://127.0.0.1:19999")
        result = client.test_connection()
        self.assertFalse(result["ok"])

    def test_headers_with_token(self):
        client = self.MoonrakerClient(base_url="http://x", api_token="abc123")
        self.assertEqual(client._headers()["X-Api-Key"], "abc123")

    def test_headers_without_token(self):
        client = self.MoonrakerClient(base_url="http://x", api_token="")
        self.assertNotIn("X-Api-Key", client._headers())


class TestSlicerBridge(unittest.TestCase):
    def setUp(self):
        from slicer_bridge import SlicerBridge
        self.SlicerBridge = SlicerBridge

    def test_not_available_when_no_cli(self):
        with patch("slicer_bridge.find_prusa_cli", return_value=None):
            bridge = self.SlicerBridge()
        self.assertFalse(bridge.available())

    def test_slice_returns_error_when_unavailable(self):
        with patch("slicer_bridge.find_prusa_cli", return_value=None):
            bridge = self.SlicerBridge()
        result = bridge.slice_model(b"fake stl data")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["gcode"])

    def test_slice_runs_prusa_slicer(self):
        with patch("slicer_bridge.find_prusa_cli", return_value="/usr/bin/prusa-slicer"):
            bridge = self.SlicerBridge()
        import subprocess
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "sliced"
        mock_result.stderr = ""
        import os
        import tempfile

        def fake_run(cmd, **kw):
            # Create the expected output file
            out = next((cmd[i + 1] for i, c in enumerate(cmd) if c == "--output"), None)
            if out:
                with open(out, "wb") as f:
                    f.write(b"; gcode\nG28\n")
            return mock_result

        with patch("slicer_bridge.subprocess.run", side_effect=fake_run):
            result = bridge.slice_model(b"fake stl", model_ext="stl")
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["gcode"])


class TestLidarDriver(unittest.TestCase):
    def setUp(self):
        from lidar_driver import LidarDriver
        self.LidarDriver = LidarDriver

    @patch("lidar_driver.serial.Serial", side_effect=Exception("no port"))
    def test_open_failure(self, _):
        driver = self.LidarDriver(port="/dev/null")
        ok = driver.open()
        self.assertFalse(ok)

    def test_read_returns_none_when_not_open(self):
        driver = self.LidarDriver(port="/dev/null")
        with patch.object(driver, "open", return_value=False):
            result = driver.read_distance_mm()
        self.assertIsNone(result)


class TestSettingsHelpers(unittest.TestCase):
    def test_load_save_settings(self):
        import json
        import tempfile
        import os

        import klipper_client as kc

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"foo": "bar"}, f)
            name = f.name

        orig_path = kc.SETTINGS_FILE
        kc.SETTINGS_FILE = name
        try:
            data = kc.load_settings()
            self.assertEqual(data["foo"], "bar")
            kc.save_settings({"baz": 42})
            data2 = kc.load_settings()
            self.assertEqual(data2["baz"], 42)
        finally:
            kc.SETTINGS_FILE = orig_path
            os.unlink(name)


if __name__ == "__main__":
    unittest.main()
