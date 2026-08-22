import unittest

from software.app.usb_driver import CrealityUsbDriver
from software.tests.helpers import FakeTransport


class TestCrealityUsbDriver(unittest.TestCase):
    def test_move_formats_command(self):
        transport = FakeTransport([b"OK MOVE\n"])
        driver = CrealityUsbDriver(transport=transport)

        response = driver.move("x", 120, 300)

        self.assertEqual("OK MOVE", response)
        self.assertEqual([b"MOVE X 120 300\n"], transport.writes)

    def test_read_endstop_y(self):
        transport = FakeTransport([b"OK ENDSTOP 1\n"])
        driver = CrealityUsbDriver(transport=transport)

        self.assertTrue(driver.read_endstop_y())

    def test_error_response_raises(self):
        transport = FakeTransport([b"ERR UNKNOWN\n"])
        driver = CrealityUsbDriver(transport=transport)

        with self.assertRaises(RuntimeError):
            driver.ping()

    def test_sync_token_with_space_rejected(self):
        driver = CrealityUsbDriver(transport=FakeTransport([]))
        with self.assertRaises(ValueError):
            driver.sync("bad token")


if __name__ == "__main__":
    unittest.main()
