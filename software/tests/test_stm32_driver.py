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

    def test_motor_home_all_and_api_aliases(self):
        driver = STM32Driver()
        commands = []
        driver._send_command = lambda cmd: commands.append(cmd) or True

        result = driver.home_motor("all")

        self.assertEqual(set(result), {"X", "Y", "Z"})
        self.assertEqual(commands, ["HOME_X", "HOME_Y", "HOME_Z"])
        self.assertEqual(driver.get_motor_status()["protocol"], "serial_text")

    def test_temperature_accepts_embedded_value_only_from_ok_response(self):
        class FakeSerial:
            def __init__(self, response):
                self.response = response

            def write(self, _):
                pass

            def readline(self):
                return self.response.encode("ascii")

        driver = STM32Driver()
        driver._serial = FakeSerial("OK TEMP=42.5\n")
        self.assertEqual(driver.read_board_temperature(), 42.5)

        driver._serial = FakeSerial("ERR TEMP=99.0\n")
        self.assertIsNone(driver.read_board_temperature())


if __name__ == "__main__":
    unittest.main()
