import struct
import unittest

from firmware.raspberry_pi.usb_driver import (
    CMD_MOVE_X,
    CMD_GET_TEMP,
    CMD_FAN_ON,
    CMD_FAN_OFF,
    CMD_SET_FAN_THRESHOLD,
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


def build_response(status=STATUS_OK, error=0, pos_x=0, pos_y=0, pos_z=0, endstop_mask=0, temperature_cdeg=2500):
    head = struct.pack("<BBiiiBh", status, error, pos_x, pos_y, pos_z, endstop_mask, temperature_cdeg)
    checksum = USBScannerDriver.checksum(head)
    return struct.pack(RESPONSE_FORMAT, status, error, pos_x, pos_y, pos_z, endstop_mask, temperature_cdeg, checksum)


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

    def test_home_and_set_speed_commands(self):
        transport = FakeTransport(build_response())
        driver = USBScannerDriver(transport)

        driver.home_x()
        self.assertEqual(transport.last_payload[0], 0x10)

        driver.set_speed("Y", 1200)
        self.assertEqual(transport.last_payload[0], 0x20)
        self.assertEqual(transport.last_payload[1], 1)

    def test_set_speed_invalid_axis_raises(self):
        transport = FakeTransport(build_response())
        driver = USBScannerDriver(transport)

        with self.assertRaises(ValueError):
            driver.set_speed("Q", 1200)

    def test_get_temperature_returns_celsius(self):
        # temperature_cdeg = 4530 → 45.30 °C
        transport = FakeTransport(build_response(temperature_cdeg=4530))
        driver = USBScannerDriver(transport)

        temp = driver.get_temperature()

        self.assertAlmostEqual(temp, 45.30, places=2)
        self.assertEqual(transport.last_payload[0], CMD_GET_TEMP)

    def test_fan_on_sends_command(self):
        transport = FakeTransport(build_response())
        driver = USBScannerDriver(transport)

        driver.fan_on()

        self.assertEqual(transport.last_payload[0], CMD_FAN_ON)

    def test_fan_off_sends_command(self):
        transport = FakeTransport(build_response())
        driver = USBScannerDriver(transport)

        driver.fan_off()

        self.assertEqual(transport.last_payload[0], CMD_FAN_OFF)

    def test_set_fan_threshold_sends_correct_values(self):
        transport = FakeTransport(build_response())
        driver = USBScannerDriver(transport)

        driver.set_fan_threshold(50.0, 45.0)

        self.assertEqual(transport.last_payload[0], CMD_SET_FAN_THRESHOLD)
        # Decode value (on) and speed (off) from packet bytes 2..10 (two int32 LE)
        _, _, value, speed, _ = struct.unpack("<BBiiB", transport.last_payload)
        self.assertEqual(value, 5000)   # 50.0 * 100
        self.assertEqual(speed, 4500)   # 45.0 * 100

    def test_set_fan_threshold_invalid_raises(self):
        transport = FakeTransport(build_response())
        driver = USBScannerDriver(transport)

        with self.assertRaises(ValueError):
            driver.set_fan_threshold(45.0, 50.0)  # on <= off → invalid


if __name__ == "__main__":
    unittest.main()
