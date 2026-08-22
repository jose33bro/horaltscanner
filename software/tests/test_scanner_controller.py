import unittest

from software.app.pi_hardware import LaserController, SensorRig
from software.app.scanner_controller import ScanController
from software.app.usb_driver import CrealityUsbDriver
from software.tests.helpers import FakeTransport


class RecordingLaser(LaserController):
    def __init__(self):
        super().__init__(left_gpio_pin=17, right_gpio_pin=27)
        self.calls = []

    def set_state(self, left_on: bool, right_on: bool) -> None:
        self.calls.append((left_on, right_on))


class TestScanController(unittest.TestCase):
    def test_acquire_scan_step_returns_sync_payload(self):
        usb = CrealityUsbDriver(FakeTransport([b"OK MOVE\n", b"OK SYNC token42\n"]))
        lasers = RecordingLaser()
        controller = ScanController(
            usb=usb,
            lasers=lasers,
            sensors=SensorRig(
                lidar_port="/dev/ttyUSB0",
                usb_camera_id="logitech-0",
                dsi_camera_id="picam-v3",
            ),
        )

        payload = controller.acquire_scan_step(20, "token42")

        self.assertEqual("OK SYNC token42", payload["sync"])
        self.assertIn("lidar_distance_mm", payload)
        self.assertEqual([(True, True), (False, False)], lasers.calls)


if __name__ == "__main__":
    unittest.main()
