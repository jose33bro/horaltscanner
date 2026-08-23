import struct
import unittest

from firmware.raspberry_pi.usb_driver import CMD_GET_STATUS, CMD_MOVE_X, RESPONSE_FORMAT, STATUS_OK, USBScannerDriver
from software.drivers.stm32_driver import STM32Driver


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def exchange(self, payload: bytes) -> bytes:
        self.payloads.append(payload)
        return self.responses.pop(0)


def build_response(status=STATUS_OK, error=0, pos_x=0, pos_y=0, pos_z=0, endstop_mask=0):
    head = struct.pack("<BBiiiB", status, error, pos_x, pos_y, pos_z, endstop_mask)
    checksum = USBScannerDriver.checksum(head)
    return struct.pack(RESPONSE_FORMAT, status, error, pos_x, pos_y, pos_z, endstop_mask, checksum)


class STM32DriverTests(unittest.TestCase):
    def test_connect_syncs_binary_status(self):
        transport = FakeTransport(
            [
                build_response(pos_x=800, pos_z=400, endstop_mask=0b101),
                build_response(pos_x=800, pos_z=400, endstop_mask=0b101),
            ]
        )
        driver = STM32Driver(transport=transport)

        self.assertTrue(driver.connect())

        status = driver.motor_status()
        self.assertEqual(transport.payloads[0][0], CMD_GET_STATUS)
        self.assertTrue(status["connected"])
        self.assertAlmostEqual(status["axes"]["X"]["position_mm"], 10.0, places=3)
        self.assertAlmostEqual(status["axes"]["Z"]["position_mm"], 1.0, places=3)
        self.assertTrue(status["axes"]["X"]["homed"])
        self.assertTrue(status["axes"]["Z"]["homed"])

    def test_move_uses_binary_axis_command(self):
        transport = FakeTransport([build_response(), build_response(pos_x=800, endstop_mask=0b001)])
        driver = STM32Driver(transport=transport)
        driver.connect()

        result = driver.motor_move("X", 10.0, velocity_mm_s=20.0)

        self.assertEqual(transport.payloads[1][0], CMD_MOVE_X)
        self.assertEqual(result["axis"], "X")
        self.assertAlmostEqual(result["position_mm"], 10.0, places=3)

    def test_move_rejects_velocity_above_configured_limit(self):
        transport = FakeTransport([build_response()])
        driver = STM32Driver(transport=transport)
        driver.connect()

        with self.assertRaises(ValueError):
            driver.motor_move("Z", 1.0, velocity_mm_s=99.0)


if __name__ == "__main__":
    unittest.main()
