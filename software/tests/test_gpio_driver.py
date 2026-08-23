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


if __name__ == "__main__":
    unittest.main()
