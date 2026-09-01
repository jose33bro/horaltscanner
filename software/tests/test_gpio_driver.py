import unittest
from unittest.mock import Mock

from software.drivers.gpio_driver import GPIODriver


class GPIODriverTests(unittest.TestCase):
    def test_driver_uses_hardware_config_pins(self):
        driver = GPIODriver(
            simulation=True,
            hardware_config={
                "lasers": {"left": {"gpio": 5}, "right": {"gpio": 6}},
                "led_rgb": {"red": {"gpio": 12}, "green": {"gpio": 16}, "blue": {"gpio": 20}},
                "fans": {"pi_fan": {"gpio": 21}},
            },
        )

        status = driver.status()

        self.assertTrue(status["simulation"])
        self.assertFalse(status["hardware_available"])
        self.assertEqual(status["pins"]["laser_left"], 5)
        self.assertEqual(status["pins"]["laser_right"], 6)
        self.assertEqual(status["pins"]["led_r"], 12)
        self.assertEqual(status["pins"]["fan_pi"], 21)

    def test_unknown_led_mode_is_rejected(self):
        driver = GPIODriver(simulation=True)

        with self.assertRaises(ValueError):
            driver.led_set_mode("strobe")

    def test_connect_returns_true(self):
        driver = GPIODriver(simulation=True)
        self.assertTrue(driver.connect())
        self.assertTrue(driver.simulation)
        self.assertTrue(driver.hardware_available)

    def test_connect_initializes_pi_fan_from_hardware_config(self):
        fan_device = Mock()
        factory = Mock(return_value=fan_device)
        driver = GPIODriver(
            simulation=False,
            hardware_config={
                "fans": {
                    "pi_fan": {
                        "gpio": 23,
                        "active_high": True,
                        "default_value": 0,
                    }
                }
            },
            output_device_factory=factory,
        )

        self.assertTrue(driver.connect())
        factory.assert_called_once_with(23, True, False)
        self.assertTrue(driver.status()["hardware_available"])
        self.assertEqual(driver.get_fan_status()["speed"], 0.0)

        self.assertTrue(driver.set_fan_speed(0.4))
        fan_device.on.assert_called_once_with()
        self.assertEqual(driver.get_fan_status()["speed"], 1.0)

        self.assertTrue(driver.set_fan_speed(0.0))
        fan_device.off.assert_called_once_with()
        self.assertEqual(driver.get_fan_status()["speed"], 0.0)

    def test_read_cpu_temperature_uses_injected_reader(self):
        driver = GPIODriver(
            simulation=True,
            cpu_temperature_reader=lambda: 48.75,
        )

        self.assertEqual(driver.read_cpu_temperature(), 48.75)

    def test_real_gpio_outputs_use_active_high_devices(self):
        output_devices = [Mock(), Mock(), Mock()]
        pwm_devices = [Mock(), Mock(), Mock()]
        output_factory = Mock(side_effect=output_devices)
        pwm_factory = Mock(side_effect=pwm_devices)
        driver = GPIODriver(
            simulation=False,
            hardware_config={
                "lasers": {
                    "left": {"gpio": 27, "active_high": True},
                    "right": {"gpio": 22, "active_high": True},
                },
                "led_rgb": {
                    "active_high": True,
                    "pwm_frequency_hz": 100,
                    "red": {"gpio": 18},
                    "green": {"gpio": 13},
                    "blue": {"gpio": 19},
                },
                "fans": {"pi_fan": {"gpio": 23, "default_value": 0}},
            },
            output_device_factory=output_factory,
            pwm_device_factory=pwm_factory,
        )

        self.assertTrue(driver.connect())
        self.assertEqual(
            output_factory.call_args_list,
            [
                unittest.mock.call(27, True, False),
                unittest.mock.call(22, True, False),
                unittest.mock.call(23, True, False),
            ],
        )
        self.assertTrue(driver.laser_on("left"))
        output_devices[0].on.assert_called_once_with()
        self.assertTrue(driver.laser_off("left"))
        output_devices[0].off.assert_called_once_with()

        self.assertTrue(driver.led_set(255, 128, 0))
        self.assertEqual(pwm_devices[0].value, 1.0)
        self.assertAlmostEqual(pwm_devices[1].value, 128 / 255.0)
        self.assertEqual(pwm_devices[2].value, 0.0)
        self.assertEqual(driver.get_fan_status()["speed"], 0.0)

    def test_real_fan_rejects_commands_when_gpio_is_unavailable(self):
        driver = GPIODriver(
            simulation=False,
            hardware_config={"fans": {"pi_fan": {"gpio": 23}}},
            output_device_factory=Mock(side_effect=RuntimeError("GPIO busy")),
        )

        self.assertFalse(driver.connect())
        self.assertFalse(driver.set_fan_speed(1.0))

    def test_close_releases_pi_fan_gpio(self):
        fan_device = Mock()
        driver = GPIODriver(
            simulation=False,
            hardware_config={"fans": {"pi_fan": {"gpio": 23}}},
            output_device_factory=Mock(return_value=fan_device),
        )
        driver.connect()

        driver.close()

        fan_device.close.assert_called_once_with()
        self.assertFalse(driver.status()["hardware_available"])
        self.assertEqual(driver.get_fan_status()["speed"], 0.0)

    def test_laser_on_and_off_update_status(self):
        driver = GPIODriver(simulation=True)

        self.assertTrue(driver.laser_on("left"))
        self.assertTrue(driver.get_laser_status()["left"])
        self.assertFalse(driver.get_laser_status()["right"])

        self.assertTrue(driver.laser_off("left"))
        self.assertFalse(driver.get_laser_status()["left"])

    def test_laser_unknown_side_returns_false(self):
        driver = GPIODriver(simulation=True)
        self.assertFalse(driver.laser_on("center"))
        self.assertFalse(driver.laser_off("center"))

    def test_led_set_and_get_status(self):
        driver = GPIODriver(simulation=True)

        self.assertTrue(driver.led_set(100, 150, 200))
        self.assertEqual(driver.get_led_status(), {"r": 100, "g": 150, "b": 200})

    def test_set_fan_speed_clamps_and_updates_status(self):
        driver = GPIODriver(simulation=True, temperature_reader=lambda: 40.0)

        self.assertTrue(driver.set_fan_speed(0.75))
        self.assertEqual(driver.get_fan_status()["speed"], 1.0)

        self.assertTrue(driver.set_fan_speed(2.0))
        self.assertAlmostEqual(driver.get_fan_status()["speed"], 1.0)

        self.assertTrue(driver.set_fan_speed(-1.0))
        self.assertAlmostEqual(driver.get_fan_status()["speed"], 0.0)

    def test_pi_fan_auto_control_uses_temperature_hysteresis(self):
        temperatures = iter((56.0, 50.0, 44.0))
        driver = GPIODriver(
            simulation=True,
            hardware_config={
                "fans": {
                    "pi_fan": {
                        "auto_control": True,
                        "on_temp_c": 55,
                        "off_temp_c": 45,
                    }
                }
            },
            temperature_reader=lambda: next(temperatures),
        )

        self.assertTrue(driver.update_pi_fan_auto_control())
        self.assertEqual(driver._pi_fan_speed, 1.0)
        self.assertTrue(driver.update_pi_fan_auto_control())
        self.assertEqual(driver._pi_fan_speed, 1.0)
        self.assertTrue(driver.update_pi_fan_auto_control())
        self.assertEqual(driver._pi_fan_speed, 0.0)

    def test_pi_fan_auto_control_fails_safe_on_temperature_error(self):
        driver = GPIODriver(
            simulation=True,
            hardware_config={"fans": {"pi_fan": {"auto_control": True}}},
            temperature_reader=Mock(side_effect=OSError("sensor unavailable")),
        )

        self.assertTrue(driver.update_pi_fan_auto_control())
        self.assertEqual(driver._pi_fan_speed, 1.0)

    def test_pi_fan_rejects_invalid_temperature_thresholds(self):
        with self.assertRaises(ValueError):
            GPIODriver(
                hardware_config={
                    "fans": {
                        "pi_fan": {
                            "on_temp_c": 45,
                            "off_temp_c": 55,
                        }
                    }
                }
            )


if __name__ == "__main__":
    unittest.main()
