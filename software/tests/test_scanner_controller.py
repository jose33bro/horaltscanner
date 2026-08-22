import unittest

from software.app.pi_hardware import LaserController, SensorRig
from software.app.scanner_controller import ScanController
from software.app.usb_driver import CrealityUsbDriver


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)

    def write(self, payload: bytes) -> None:
        _ = payload

    def read_line(self) -> bytes:
        return self.responses.pop(0)


class TestScanController(unittest.TestCase):
    def test_acquire_scan_step_returns_sync_payload(self):
        usb = CrealityUsbDriver(FakeTransport([b"OK MOVE\n", b"OK SYNC token42\n"]))
        controller = ScanController(
            usb=usb,
            lasers=LaserController(left_gpio_pin=17, right_gpio_pin=27),
            sensors=SensorRig(
                lidar_port="/dev/ttyUSB0",
                usb_camera_id="logitech-0",
                dsi_camera_id="picam-v3",
            ),
        )

        payload = controller.acquire_scan_step(20, "token42")

        self.assertEqual("OK SYNC token42", payload["sync"])
        self.assertIn("lidar_distance_mm", payload)


if __name__ == "__main__":
    unittest.main()
