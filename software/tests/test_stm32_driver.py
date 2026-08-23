import unittest

from software.drivers.stm32_driver import STM32Driver


class STM32DriverFanAndTemperatureTests(unittest.TestCase):
    def test_set_fan_speed_uses_pa0_for_creality(self):
        driver = STM32Driver()
        commands = []
        driver._send_command = lambda cmd: commands.append(cmd) or True

        success = driver.set_fan_speed("creality", 0.5)

        self.assertTrue(success)
        self.assertEqual(commands, ["FAN_PA0_PWM 127"])
        self.assertEqual(driver.get_fan_status()["creality"], 0.5)

    def test_set_fan_speed_uses_pa8_for_temperature_fan_and_clamps_speed(self):
        driver = STM32Driver()
        commands = []
        driver._send_command = lambda cmd: commands.append(cmd) or True

        success = driver.set_fan_speed("temperature", 1.5)

        self.assertTrue(success)
        self.assertEqual(commands, ["FAN_PA8_PWM 255"])
        self.assertEqual(driver.get_fan_status()["temperature"], 1.0)

    def test_read_temperature_alias_calls_board_reader(self):
        driver = STM32Driver()
        driver.read_board_temperature = lambda: 41.2

        self.assertEqual(driver.read_temperature(), 41.2)


if __name__ == "__main__":
    unittest.main()
