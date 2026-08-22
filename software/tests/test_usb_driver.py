import struct
import unittest

from firmware.raspberry_pi.usb_driver import (
    CMD_MOVE_X,
    RESPONSE_FORMAT,
    STATUS_OK,
    USBProtocolError,
    USBScannerDriver,
)


class FakeTransport:
    def __init__(self, response: bytes):
        self.response = response
        self.last_payload = b""

    def exchange(self, payload: bytes) -> bytes:
        self.last_payload = payload
        return self.response


def build_response(status=STATUS_OK, error=0, pos_x=0, pos_y=0, pos_z=0, endstop_mask=0):
    head = struct.pack("<BBiiiB", status, error, pos_x, pos_y, pos_z, endstop_mask)
    checksum = USBScannerDriver.checksum(head)
    return struct.pack(RESPONSE_FORMAT, status, error, pos_x, pos_y, pos_z, endstop_mask, checksum)


class USBDriverTests(unittest.TestCase):
    def test_move_x_sends_command_and_parses_response(self):
        transport = FakeTransport(build_response(pos_x=120, pos_y=10, pos_z=5, endstop_mask=0b101))
        driver = USBScannerDriver(transport)

        status = driver.move_x(120, speed=1000)

        self.assertEqual(status.pos_x, 120)
        self.assertEqual(status.endstop_mask, 0b101)
        self.assertEqual(transport.last_payload[0], CMD_MOVE_X)

    def test_bad_checksum_raises(self):
        bad_response = bytearray(build_response(pos_x=5))
        bad_response[-1] ^= 0xFF
        transport = FakeTransport(bytes(bad_response))
        driver = USBScannerDriver(transport)

        with self.assertRaises(USBProtocolError):
            driver.get_status()


if __name__ == "__main__":
    unittest.main()
