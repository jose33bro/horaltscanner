import unittest

from firmware.raspberry_pi.fan_gpio_control import FanGPIOController, OverheatError
from firmware.raspberry_pi.gpio_laser_control import LaserController
from firmware.raspberry_pi.motor_control import MotorController
from firmware.raspberry_pi.scanner_app import ScannerApp, ScanAbortedError
from firmware.raspberry_pi.usb_driver import ScannerStatus


class FakeGPIO:
    def __init__(self):
        self.writes = []

    def setup_output(self, pin):
        self.writes.append(("setup", pin))

    def write(self, pin, value):
        self.writes.append(("write", pin, value))


class FanGPIOControllerTests(unittest.TestCase):
    def _make_fan(self, **kwargs):
        gpio = FakeGPIO()
        fan = FanGPIOController(gpio, pin=17, **kwargs)
        return fan, gpio

    def test_initial_state_is_off(self):
        fan, _ = self._make_fan()
        self.assertFalse(fan.is_on)

    def test_fan_on_and_off(self):
        fan, gpio = self._make_fan()
        fan.fan_on()
        self.assertTrue(fan.is_on)
        self.assertIn(("write", 17, True), gpio.writes)

        fan.fan_off()
        self.assertFalse(fan.is_on)
        self.assertIn(("write", 17, False), gpio.writes)

    def test_update_turns_on_above_threshold(self):
        fan, _ = self._make_fan()
        fan.update(49.9)
        self.assertFalse(fan.is_on)

        fan.update(50.1)
        self.assertTrue(fan.is_on)

    def test_update_turns_off_below_threshold_hysteresis(self):
        fan, _ = self._make_fan()
        fan.fan_on()
        fan.update(46.0)  # above off threshold (45), should stay on
        self.assertTrue(fan.is_on)

        fan.update(44.9)  # below off threshold
        self.assertFalse(fan.is_on)

    def test_update_emergency_raises_and_turns_off(self):
        emergency_temps = []
        fan, _ = self._make_fan(on_emergency=emergency_temps.append)
        fan.fan_on()

        with self.assertRaises(OverheatError):
            fan.update(60.5)

        self.assertFalse(fan.is_on)
        self.assertEqual(len(emergency_temps), 1)
        self.assertAlmostEqual(emergency_temps[0], 60.5)

    def test_invalid_thresholds_raise(self):
        gpio = FakeGPIO()
        with self.assertRaises(ValueError):
            FanGPIOController(gpio, pin=17, fan_on_celsius=45.0, fan_off_celsius=50.0)

    def test_set_thresholds_updates_at_runtime(self):
        fan, _ = self._make_fan()
        fan.set_thresholds(40.0, 35.0)
        fan.update(39.9)
        self.assertFalse(fan.is_on)
        fan.update(40.1)
        self.assertTrue(fan.is_on)


# ---------------------------------------------------------------------------
# ScannerApp thermal integration tests
# ---------------------------------------------------------------------------

class FakeDriver:
    def __init__(self):
        self.calls = []
        self.pos_x = 0
        self.pos_y = 0
        self.pos_z = 0

    def _status(self):
        return ScannerStatus(status=0, error=0, pos_x=self.pos_x, pos_y=self.pos_y, pos_z=self.pos_z, endstop_mask=0)

    def home_x(self):
        self.calls.append("home_x"); self.pos_x = 0; return self._status()

    def home_y(self):
        self.calls.append("home_y"); self.pos_y = 0; return self._status()

    def home_z(self):
        self.calls.append("home_z"); self.pos_z = 0; return self._status()

    def move_x(self, steps, speed=0):
        self.calls.append(("move_x", steps, speed)); self.pos_x += steps; return self._status()

    def move_y(self, steps, speed=0):
        self.calls.append(("move_y", steps, speed)); self.pos_y += steps; return self._status()

    def move_z(self, steps, speed=0):
        self.calls.append(("move_z", steps, speed)); self.pos_z += steps; return self._status()


class FakeSensors:
    def capture(self):
        return {}


class FakeTemp:
    def __init__(self, temp):
        self.temp = temp

    def get_temperature(self):
        return self.temp


class ScannerAppThermalTests(unittest.TestCase):
    def _make_app(self, temp_value):
        driver = FakeDriver()
        controller = MotorController(driver)
        gpio = FakeGPIO()
        lasers = LaserController(gpio, left_pin=17, right_pin=27)
        sensors = FakeSensors()
        fan_gpio = FakeGPIO()
        fan = FanGPIOController(fan_gpio, pin=22)
        temp_src = FakeTemp(temp_value)
        return ScannerApp(controller, lasers, sensors, temp_source=temp_src, fan_controller=fan)

    def test_scan_succeeds_at_safe_temperature(self):
        app = self._make_app(30.0)
        frames = app.run_scan(x_offsets=[10], z_offsets=[5], rotation_steps=2, step_per_rotation=90)
        self.assertEqual(len(frames), 2)

    def test_scan_aborted_if_temp_exceeds_pre_scan_limit(self):
        app = self._make_app(56.0)
        with self.assertRaises(ScanAbortedError):
            app.run_scan(x_offsets=[10], z_offsets=[5], rotation_steps=2, step_per_rotation=90)

    def test_scan_aborted_on_emergency_during_capture(self):
        # Temperature below pre-scan limit but above emergency threshold during scan
        app = self._make_app(61.0)
        # Pre-scan check uses 61 > 55, raises before scan starts
        with self.assertRaises(ScanAbortedError):
            app.run_scan(x_offsets=[10], z_offsets=[5], rotation_steps=2, step_per_rotation=90)


if __name__ == "__main__":
    unittest.main()
