import threading
import time
import unittest

from software.api.lidar_driver import (
    LidarDriver,
    TFLUNA_OUTPUT_DISABLE,
    TFLUNA_OUTPUT_ENABLE,
)


class _Serial:
    is_open = True

    def __init__(self):
        self.writes = []
        self.flushes = 0
        self.resets = 0
        self.write_timeout = 0.5

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        self.flushes += 1

    def reset_input_buffer(self):
        self.resets += 1


class _BlockingReadSerial(_Serial):
    def __init__(self):
        super().__init__()
        self.read_entered = threading.Event()
        self.release_read = threading.Event()
        self.responses = iter(
            (b"\x59", b"\x59", bytes((29, 0, 0, 0, 0, 0, 0)))
        )

    def read(self, _size):
        if not self.read_entered.is_set():
            self.read_entered.set()
            self.release_read.wait(1)
        return next(self.responses)


class _BlockingFlushSerial(_Serial):
    def __init__(self):
        super().__init__()
        self.flush_entered = threading.Event()

    def flush(self):
        self.flush_entered.set()
        threading.Event().wait(1)


class LidarDriverTests(unittest.TestCase):
    def setUp(self):
        self.driver = LidarDriver()
        self.serial = _Serial()
        self.driver._ser = self.serial

    def test_output_commands_use_verified_tfluna_frames(self):
        self.assertTrue(self.driver.set_output_enabled(False))
        self.assertTrue(self.driver.set_output_enabled(True))
        self.assertEqual(
            self.serial.writes,
            [TFLUNA_OUTPUT_DISABLE, TFLUNA_OUTPUT_ENABLE],
        )
        self.assertEqual(TFLUNA_OUTPUT_DISABLE, bytes.fromhex("5A05070066"))
        self.assertEqual(TFLUNA_OUTPUT_ENABLE, bytes.fromhex("5A05070167"))
        self.assertEqual(self.serial.flushes, 0)
        self.assertEqual(self.serial.resets, 0)
        self.assertEqual(self.serial.write_timeout, 0.5)

    def test_output_command_reports_short_write(self):
        self.serial.write = lambda _data: 2
        self.assertFalse(self.driver.set_output_enabled(False))

    def test_output_command_reports_disconnected_device(self):
        self.serial.is_open = False
        self.assertFalse(self.driver.set_output_enabled(True))
        self.assertEqual(self.serial.writes, [])

    def test_output_commands_never_call_potentially_blocking_flush(self):
        serial = _BlockingFlushSerial()
        self.driver._ser = serial
        started = time.monotonic()

        self.assertTrue(self.driver.set_output_enabled(False, timeout_s=0.05))
        self.assertTrue(self.driver.set_output_enabled(True, timeout_s=0.05))

        self.assertLess(time.monotonic() - started, 0.2)
        self.assertFalse(serial.flush_entered.is_set())
        self.assertEqual(
            serial.writes,
            [TFLUNA_OUTPUT_DISABLE, TFLUNA_OUTPUT_ENABLE],
        )

    def test_output_command_waits_for_in_progress_read(self):
        serial = _BlockingReadSerial()
        self.driver._ser = serial
        distance = []
        output_result = []
        writer_started = threading.Event()

        reader = threading.Thread(
            target=lambda: distance.append(self.driver.read_distance_mm())
        )

        def enable_output():
            writer_started.set()
            output_result.append(self.driver.set_output_enabled(True))

        writer = threading.Thread(target=enable_output)
        reader.start()
        self.assertTrue(serial.read_entered.wait(1))
        writer.start()
        self.assertTrue(writer_started.wait(1))
        time.sleep(0.02)
        self.assertEqual(serial.writes, [])
        serial.release_read.set()
        reader.join(1)
        writer.join(1)

        self.assertEqual(distance, [290.0])
        self.assertEqual(output_result, [True])
        self.assertEqual(serial.writes, [TFLUNA_OUTPUT_ENABLE])


if __name__ == "__main__":
    unittest.main()
