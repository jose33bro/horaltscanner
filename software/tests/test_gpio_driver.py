import unittest

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
        driver = GPIODriver(simulation=True)

        self.assertTrue(driver.set_fan_speed(0.75))
        self.assertAlmostEqual(driver.get_fan_status()["speed"], 0.75)

        self.assertTrue(driver.set_fan_speed(2.0))
        self.assertAlmostEqual(driver.get_fan_status()["speed"], 1.0)

        self.assertTrue(driver.set_fan_speed(-1.0))
        self.assertAlmostEqual(driver.get_fan_status()["speed"], 0.0)


if __name__ == "__main__":
    unittest.main()
