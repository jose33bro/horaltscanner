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

    def test_connect_returns_true(self):
        driver = STM32Driver()
        self.assertTrue(driver.connect())

    def test_move_motor_updates_position(self):
        driver = STM32Driver()
        commands = []
        driver._send_command = lambda cmd: commands.append(cmd) or True

        self.assertTrue(driver.move_motor("x", 10.0))
        self.assertAlmostEqual(driver.get_motor_status()["positions"]["x"], 10.0)
        self.assertEqual(commands, ["MOVE_X 10.0"])

    def test_move_motor_unknown_axis_returns_false(self):
        driver = STM32Driver()
        self.assertFalse(driver.move_motor("w", 5.0))

    def test_home_motor_resets_position(self):
        driver = STM32Driver()
        driver.move_motor("y", 20.0)

        self.assertTrue(driver.home_motor("y"))
        self.assertAlmostEqual(driver.get_motor_status()["positions"]["y"], 0.0)

    def test_home_all_resets_all_positions(self):
        driver = STM32Driver()
        driver.move_motor("x", 5.0)
        driver.move_motor("z", 3.0)

        self.assertTrue(driver.home_motor("all"))
        status = driver.get_motor_status()
        self.assertAlmostEqual(status["positions"]["x"], 0.0)
        self.assertAlmostEqual(status["positions"]["z"], 0.0)

    def test_stop_motor_all(self):
        driver = STM32Driver()
        commands = []
        driver._send_command = lambda cmd: commands.append(cmd) or True

        self.assertTrue(driver.stop_motor("all"))
        self.assertIn("STOP_ALL", commands)

    def test_stop_motor_single_axis(self):
        driver = STM32Driver()
        commands = []
        driver._send_command = lambda cmd: commands.append(cmd) or True

        self.assertTrue(driver.stop_motor("x"))
        self.assertIn("STOP_X", commands)

    def test_stop_motor_unknown_axis_returns_false(self):
        driver = STM32Driver()
        self.assertFalse(driver.stop_motor("w"))


if __name__ == "__main__":
    unittest.main()
