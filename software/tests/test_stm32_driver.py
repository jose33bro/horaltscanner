import unittest
from unittest.mock import Mock

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

    def test_connect_opens_configured_serial_port(self):
        serial_port = Mock()
        serial_factory = Mock(return_value=serial_port)
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {
                    "mcu_port": "/dev/ttyUSB1",
                    "baud": 115200,
                    "timeout_s": 0.5,
                }
            },
            serial_factory=serial_factory,
        )

        self.assertTrue(driver.connect())
        serial_factory.assert_called_once_with(
            "/dev/ttyUSB1",
            115200,
            timeout=0.5,
            write_timeout=0.5,
        )
        serial_port.reset_input_buffer.assert_called_once_with()

    def test_read_board_temperature_from_pc5_response(self):
        serial_port = Mock()
        serial_port.readline.return_value = b"OK TEMP_PC5 42.6\n"
        driver = STM32Driver(
            simulation=False,
            hardware_config={"serial": {"mcu_port": "/dev/ttyUSB1"}},
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()

        self.assertEqual(driver.read_board_temperature(), 42.6)
        serial_port.write.assert_called_once_with(b"TEMP_PC5_READ\n")
        self.assertEqual(driver.get_motor_status()["temperature_c"], 42.6)

    def test_invalid_pc5_response_is_rejected(self):
        serial_port = Mock()
        serial_port.readline.return_value = b"OK TEMP_PC5 invalid\n"
        driver = STM32Driver(
            simulation=False,
            hardware_config={"serial": {"mcu_port": "/dev/ttyUSB1"}},
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()

        self.assertIsNone(driver.read_board_temperature())

    def test_move_motor_updates_position(self):
        driver = STM32Driver()
        commands = []
        driver._send_command = lambda cmd: commands.append(cmd) or True
        driver.home_motor("x")
        commands.clear()

        self.assertTrue(driver.move_motor("x", 10.0))
        self.assertAlmostEqual(driver.get_motor_status()["positions"]["x"], 10.0)
        self.assertEqual(commands, ["MOVE X 32000 160000"])

    def test_move_motor_unknown_axis_returns_false(self):
        driver = STM32Driver()
        self.assertFalse(driver.move_motor("w", 5.0))

    def test_home_motor_resets_position(self):
        driver = STM32Driver()
        driver.home_motor("y")
        driver.move_motor("y", 20.0)

        self.assertTrue(driver.home_motor("y"))
        self.assertAlmostEqual(driver.get_motor_status()["positions"]["y"], 0.0)

    def test_home_all_resets_all_positions(self):
        driver = STM32Driver()
        driver.home_motor("all")
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
        self.assertIn("STOP ALL", commands)

    def test_stop_motor_single_axis(self):
        driver = STM32Driver()
        commands = []
        driver._send_command = lambda cmd: commands.append(cmd) or True

        self.assertTrue(driver.stop_motor("x"))
        self.assertIn("STOP X", commands)

    def test_stop_motor_unknown_axis_returns_false(self):
        driver = STM32Driver()
        self.assertFalse(driver.stop_motor("w"))

    def test_move_motor_requires_homing_and_respects_limits(self):
        driver = STM32Driver(
            hardware_config={
                "motors": {
                    "x": {
                        "rotation_distance": 40,
                        "microsteps": 16,
                        "position_min": 0,
                        "position_max": 210,
                    }
                }
            }
        )

        self.assertFalse(driver.move_motor("x", 10))
        self.assertTrue(driver.home_motor("x"))
        self.assertFalse(driver.move_motor("x", -1))
        self.assertFalse(driver.move_motor("x", 211))
        self.assertTrue(driver.move_motor("x", 210))


if __name__ == "__main__":
    unittest.main()
