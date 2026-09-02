import threading
import time
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
        self.assertTrue(driver.connected)

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
        self.assertTrue(driver.connected)
        serial_factory.assert_called_once_with(
            "/dev/ttyUSB1",
            115200,
            timeout=0.5,
            write_timeout=0.5,
        )
        serial_port.reset_input_buffer.assert_called_once_with()
        self.assertTrue(driver.connected)

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

    def test_board_fan_uses_pc5_temperature_hysteresis(self):
        driver = STM32Driver(
            simulation=True,
            hardware_config={
                "temperature": {
                    "board_fan_control": {
                        "auto_control": True,
                        "on_temp_c": 39,
                        "off_temp_c": 35,
                    }
                }
            },
        )
        temperatures = iter((40.0, 40.0, 37.0, 34.0))
        commands = []
        driver.read_board_temperature = lambda: next(temperatures)
        driver.set_fan_speed = lambda channel, speed: commands.append((channel, speed)) or True

        self.assertTrue(driver.update_board_fan_auto_control())
        self.assertTrue(driver.get_temperature_status()["fan_on"])
        self.assertTrue(driver.update_board_fan_auto_control())
        self.assertTrue(driver.update_board_fan_auto_control())
        self.assertEqual(commands, [("temperature", 1.0), ("temperature", 1.0), ("temperature", 0.0)])

    def test_board_fan_fails_safe_when_pc5_is_unavailable(self):
        driver = STM32Driver(simulation=True)
        driver.read_board_temperature = lambda: None
        commands = []
        driver.set_fan_speed = lambda channel, speed: commands.append((channel, speed)) or True

        self.assertTrue(driver.update_board_fan_auto_control())
        status = driver.get_temperature_status()
        self.assertFalse(status["connected"])
        self.assertEqual(status["error"], "Temperature probe PC5 unavailable")
        self.assertEqual(commands, [("temperature", 1.0)])

    def test_move_motor_updates_position(self):
        driver = STM32Driver()
        commands = []
        driver._send_command = lambda cmd: commands.append(cmd) or True
        driver.home_motor("x")
        commands.clear()

        self.assertTrue(driver.move_motor("x", 10.0))
        self.assertAlmostEqual(driver.get_motor_status()["positions"]["x"], 10.0)
        self.assertEqual(commands, ["MOVE X 32000 20000"])

    def test_absolute_move_uses_configured_nonzero_limits(self):
        driver = STM32Driver(
            hardware_config={
                "motors": {
                    "x": {
                        "rotation_distance": 40,
                        "microsteps": 16,
                        "position_min": 10,
                        "position_max": 30,
                    }
                }
            }
        )

        self.assertEqual(driver.get_motor_limits("x"), (10.0, 30.0))
        self.assertTrue(driver.home_motor("x"))
        self.assertEqual(driver.get_motor_status()["positions"]["x"], 10.0)
        self.assertTrue(driver.move_motor_to("x", 20.0))
        self.assertEqual(driver.get_motor_status()["positions"]["x"], 20.0)
        self.assertFalse(driver.move_motor_to("x", 31.0))

    def test_real_move_stops_when_motion_status_times_out(self):
        serial_port = Mock()
        serial_port.readline.side_effect = [
            b"OK MOVE\n",
            b"OK MOTION_STATUS RUNNING\n",
            b"OK STOP\n",
        ]
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {
                    "mcu_port": "/dev/horalscanner_mcu",
                    "motion_timeout_s": 0.001,
                    "motion_poll_interval_s": 0.01,
                },
                "motors": {"x": {"rotation_distance": 40, "microsteps": 16}},
            },
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()
        driver._motor_status["homed"]["x"] = True

        self.assertFalse(driver.move_motor("x", 1.0))
        self.assertFalse(driver.get_motor_status()["homed"]["x"])
        self.assertEqual(
            [call.args[0] for call in serial_port.write.call_args_list],
            [b"MOVE X 80 4000\n", b"MOTION_STATUS\n", b"STOP X\n"],
        )

    def test_real_move_waits_for_motion_completion(self):
        serial_port = Mock()
        serial_port.readline.side_effect = [
            b"OK MOVE\n",
            b"OK MOTION_STATUS RUNNING\n",
            b"OK MOTION_STATUS DONE\n",
        ]
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {"mcu_port": "/dev/horalscanner_mcu"},
                "motors": {"x": {"rotation_distance": 40, "microsteps": 16}},
            },
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()
        driver._motor_status["homed"]["x"] = True

        self.assertTrue(driver.move_motor("x", 1.0))
        self.assertEqual(
            [call.args[0] for call in serial_port.write.call_args_list],
            [b"MOVE X 80 4000\n", b"MOTION_STATUS\n", b"MOTION_STATUS\n"],
        )

    def test_real_home_waits_for_motion_completion_before_marking_homed(self):
        serial_port = Mock()
        serial_port.readline.side_effect = [
            b"OK HOME\n",
            b"OK MOTION_STATUS RUNNING\n",
            b"OK MOTION_STATUS DONE\n",
        ]
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {"mcu_port": "/dev/horalscanner_mcu"},
                "motors": {"x": {"rotation_distance": 40, "microsteps": 16}},
            },
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()

        self.assertTrue(driver.home_motor("x"))
        self.assertTrue(driver.get_motor_status()["homed"]["x"])
        self.assertEqual(
            [call.args[0] for call in serial_port.write.call_args_list],
            [b"HOME X\n", b"MOTION_STATUS\n", b"MOTION_STATUS\n"],
        )

    def test_stopped_motion_does_not_update_position(self):
        serial_port = Mock()
        serial_port.readline.side_effect = [
            b"OK MOVE\n",
            b"OK MOTION_STATUS STOPPED\n",
        ]
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {"mcu_port": "/dev/horalscanner_mcu"},
                "motors": {"x": {"rotation_distance": 40, "microsteps": 16}},
            },
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()
        driver._motor_status["homed"]["x"] = True

        self.assertFalse(driver.move_motor("x", 1.0))
        self.assertEqual(driver.get_motor_status()["positions"]["x"], 0.0)
        self.assertFalse(driver.get_motor_status()["homed"]["x"])

    def test_serial_poll_error_invalidates_position(self):
        serial_port = Mock()
        serial_port.readline.return_value = b"OK MOVE\n"
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {"mcu_port": "/dev/horalscanner_mcu"},
                "motors": {"x": {"rotation_distance": 40, "microsteps": 16}},
            },
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()
        driver._motor_status["homed"]["x"] = True
        driver._wait_for_motion = Mock(side_effect=OSError("serial failed"))

        with self.assertRaisesRegex(OSError, "serial failed"):
            driver.move_motor("x", 1.0)

        status = driver.get_motor_status()
        self.assertFalse(status["homed"]["x"])
        self.assertFalse(status["moving"]["x"])
        self.assertEqual(status["positions"]["x"], 0.0)
        self.assertFalse(driver.connected)
        serial_port.close.assert_called_once_with()

    def test_move_acknowledgement_error_invalidates_position_and_connection(self):
        serial_port = Mock()
        serial_port.readline.side_effect = OSError("ack read failed")
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {"mcu_port": "/dev/horalscanner_mcu"},
                "motors": {"x": {"rotation_distance": 40, "microsteps": 16}},
            },
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()
        driver._motor_status["homed"]["x"] = True

        with self.assertRaisesRegex(OSError, "ack read failed"):
            driver.move_motor("x", 1.0)

        self.assertFalse(driver.get_motor_status()["homed"]["x"])
        self.assertFalse(driver.connected)
        serial_port.close.assert_called_once_with()

    def test_serial_exception_invalidates_homed_position(self):
        serial_port = Mock()
        serial_port.readline.side_effect = [
            b"OK MOVE\n",
            OSError("serial disconnected"),
        ]
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {"mcu_port": "/dev/horalscanner_mcu"},
                "motors": {"x": {"rotation_distance": 40, "microsteps": 16}},
            },
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()
        driver._motor_status["homed"]["x"] = True

        with self.assertRaises(OSError):
            driver.move_motor("x", 1.0)

        self.assertFalse(driver.get_motor_status()["homed"]["x"])
        self.assertFalse(driver.connected)

    def test_concurrent_moves_are_serialized_before_limit_check(self):
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
        driver._motor_status["homed"]["x"] = True
        driver._motor_status["positions"]["x"] = 190.0
        driver._send_command = lambda _cmd: time.sleep(0.02) or True
        results = []
        workers = [
            threading.Thread(target=lambda: results.append(driver.move_motor("x", 15.0)))
            for _ in range(2)
        ]

        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(driver.get_motor_status()["positions"]["x"], 205.0)

    def test_emergency_stop_rejects_motion_already_queued(self):
        driver = STM32Driver()
        driver._motor_status["homed"]["x"] = True
        entered = threading.Event()
        release = threading.Event()
        commands = []

        def send(command):
            commands.append(command)
            if command.startswith("MOVE"):
                entered.set()
                release.wait(1)
            return True

        driver._send_command = send
        results = []
        first = threading.Thread(target=lambda: results.append(driver.move_motor("x", 1.0)))
        second = threading.Thread(target=lambda: results.append(driver.move_motor("x", 1.0)))
        first.start()
        self.assertTrue(entered.wait(1))
        second.start()

        self.assertTrue(driver.stop_motor("all"))
        release.set()
        first.join()
        second.join()

        self.assertEqual(results, [False, False])
        self.assertEqual(sum(command.startswith("MOVE") for command in commands), 1)

    def test_move_motor_unknown_axis_returns_false(self):
        driver = STM32Driver()
        self.assertFalse(driver.move_motor("w", 5.0))

    def test_home_motor_resets_position(self):
        driver = STM32Driver()
        driver.home_motor("y")
        driver.move_motor("y", 20.0)

        self.assertTrue(driver.home_motor("y"))
        self.assertAlmostEqual(driver.get_motor_status()["positions"]["y"], 0.0)

    def test_real_home_waits_before_marking_axis_homed(self):
        serial_port = Mock()
        serial_port.readline.side_effect = [
            b"OK HOME\n",
            b"OK MOTION_STATUS RUNNING\n",
            b"OK MOTION_STATUS DONE\n",
        ]
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {
                    "mcu_port": "/dev/horalscanner_mcu",
                    "motion_poll_interval_s": 0.001,
                },
                "motors": {"x": {"rotation_distance": 40, "microsteps": 16}},
            },
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()

        self.assertTrue(driver.home_motor("x"))
        self.assertTrue(driver.get_motor_status()["homed"]["x"])
        self.assertEqual(
            [call.args[0] for call in serial_port.write.call_args_list],
            [b"HOME X\n", b"MOTION_STATUS\n", b"MOTION_STATUS\n"],
        )

    def test_home_all_resets_all_positions(self):
        driver = STM32Driver()
        driver.home_motor("all")
        driver.move_motor("x", 5.0)
        driver.move_motor("z", 3.0)

        self.assertTrue(driver.home_motor("all"))
        status = driver.get_motor_status()
        self.assertAlmostEqual(status["positions"]["x"], 0.0)
        self.assertAlmostEqual(status["positions"]["z"], 0.0)

    def test_real_home_all_waits_for_done_before_marking_axes_homed(self):
        serial_port = Mock()
        serial_port.readline.side_effect = [
            b"OK HOME\n",
            b"OK MOTION_STATUS RUNNING\n",
            b"OK MOTION_STATUS DONE\n",
        ]
        driver = STM32Driver(
            simulation=False,
            hardware_config={
                "serial": {"mcu_port": "/dev/horalscanner_mcu"},
            },
            serial_factory=Mock(return_value=serial_port),
        )
        driver.connect()

        self.assertTrue(driver.home_motor("all"))
        self.assertEqual(
            [call.args[0] for call in serial_port.write.call_args_list],
            [b"HOME ALL\n", b"MOTION_STATUS\n", b"MOTION_STATUS\n"],
        )
        self.assertTrue(all(driver.get_motor_status()["homed"].values()))

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

    def test_stop_invalidates_position_of_moving_axis(self):
        driver = STM32Driver()
        driver._send_command = lambda cmd: True
        driver._motor_status["homed"]["x"] = True
        driver._motor_status["moving"]["x"] = True

        self.assertTrue(driver.stop_motor("x"))
        self.assertFalse(driver.get_motor_status()["homed"]["x"])

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
