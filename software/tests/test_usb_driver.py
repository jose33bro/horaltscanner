import unittest

from software.app.usb_driver import CrealityUsbDriver


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.writes = []

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    def read_line(self) -> bytes:
        return self.responses.pop(0)


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


if __name__ == "__main__":
    unittest.main()
