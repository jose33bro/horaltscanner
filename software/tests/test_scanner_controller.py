import unittest

from firmware.raspberry_pi.gpio_laser_control import LaserController
from firmware.raspberry_pi.motor_control import MotorController
from firmware.raspberry_pi.scanner_app import ScannerApp
from firmware.raspberry_pi.usb_driver import ScannerStatus


class FakeDriver:
    def __init__(self):
        self.calls = []
        self.pos_x = 0
        self.pos_y = 0
        self.pos_z = 0

    def _status(self):
        return ScannerStatus(status=0, error=0, pos_x=self.pos_x, pos_y=self.pos_y, pos_z=self.pos_z, endstop_mask=0)

    def home_x(self):
        self.calls.append("home_x")
        self.pos_x = 0
        return self._status()

    def home_y(self):
        self.calls.append("home_y")
        self.pos_y = 0
        return self._status()

    def home_z(self):
        self.calls.append("home_z")
        self.pos_z = 0
        return self._status()

    def move_x(self, steps, speed=0):
        self.calls.append(("move_x", steps, speed))
        self.pos_x += steps
        return self._status()

    def move_y(self, steps, speed=0):
        self.calls.append(("move_y", steps, speed))
        self.pos_y += steps
        return self._status()

    def move_z(self, steps, speed=0):
        self.calls.append(("move_z", steps, speed))
        self.pos_z += steps
        return self._status()


class FakeGPIO:
    def __init__(self):
        self.writes = []

    def setup_output(self, pin):
        self.writes.append(("setup", pin, None))

    def write(self, pin, value):
        self.writes.append(("write", pin, value))


class FakeSensors:
    def __init__(self):
        self.frames = 0

    def capture(self):
        self.frames += 1
        return {"frame": self.frames}


class ScannerControllerTests(unittest.TestCase):
    def test_scan_sequence_captures_expected_frames(self):
        driver = FakeDriver()
        controller = MotorController(driver)
        gpio = FakeGPIO()
        lasers = LaserController(gpio, left_pin=17, right_pin=27)
        sensors = FakeSensors()
        app = ScannerApp(controller, lasers, sensors)

        frames = app.run_scan(x_offsets=[10], z_offsets=[5], rotation_steps=4, step_per_rotation=90)

        self.assertEqual(len(frames), 4)
        self.assertEqual(sensors.frames, 4)
        self.assertIn("home_x", driver.calls)
        self.assertIn(("move_y", 90, 0), driver.calls)
        self.assertEqual(frames[-1].point.status.pos_y, 360)


if __name__ == "__main__":
    unittest.main()
