import copy
import logging
import re
import threading
from typing import Any, Callable


logger = logging.getLogger(__name__)
_TEMPERATURE_RESPONSE = re.compile(r"^OK TEMP_PC5 (-?\d+(?:\.\d+)?)$")


class STM32Driver:
    def __init__(
        self,
        simulation=True,
        hardware_config=None,
        serial_factory: Callable[..., Any] | None = None,
    ):
        hardware_config = hardware_config or {}
        serial_config = hardware_config.get("serial", {})
        motors = hardware_config.get("motors", {})
        self.simulation = simulation
        self.port = serial_config.get("mcu_port")
        self.baud = int(serial_config.get("baud", 115200))
        self.timeout = float(serial_config.get("timeout_s", 1.0))
        self._serial_factory = serial_factory
        self._serial = None
        self._serial_lock = threading.Lock()
        self._steps_per_mm = {}
        self._move_speed_steps_s = {}
        self._position_min = {}
        self._position_max = {}
        for axis in ("x", "y", "z"):
            motor = motors.get(axis, {})
            microsteps = int(motor.get("microsteps", 16))
            rotation_distance = float(motor.get("rotation_distance", 1.0))
            self._steps_per_mm[axis] = (200 * microsteps) / rotation_distance
            speed_mm_s = float(motor.get("homing_speed", 50.0))
            self._move_speed_steps_s[axis] = max(1, round(speed_mm_s * self._steps_per_mm[axis]))
            self._position_min[axis] = float(motor.get("position_min", 0.0))
            self._position_max[axis] = float(motor.get("position_max", float("inf")))
        self._fan_status = {
            "creality": 0.0,
            "temperature": 0.0,
        }
        self._motor_status = {
            "positions": {"x": 0.0, "y": 0.0, "z": 0.0},
            "moving": {"x": False, "y": False, "z": False},
            "temperature_c": 0.0,
            "homed": {"x": False, "y": False, "z": False},
        }

    def connect(self):
        if self.simulation:
            return True
        if self._serial is not None:
            return True
        if not self.port:
            logger.error("Creality MCU serial port is not configured")
            return False

        try:
            if self._serial_factory is None:
                import serial

                self._serial_factory = serial.Serial
            self._serial = self._serial_factory(
                self.port,
                self.baud,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
            self._serial.reset_input_buffer()
        except Exception:
            self._serial = None
            logger.exception("Failed to open Creality MCU serial port %s", self.port)
            return False
        return True

    @property
    def connected(self):
        return self.simulation or self._serial is not None

    def _exchange(self, command):
        if self.simulation:
            return "OK"
        if self._serial is None:
            raise ConnectionError("Creality MCU is not connected")

        with self._serial_lock:
            self._serial.write((command + "\n").encode("ascii"))
            self._serial.flush()
            response = self._serial.readline().decode("ascii", errors="replace").strip()

        if not response:
            raise TimeoutError(f"No response to Creality MCU command: {command}")
        return response

    def _send_command(self, cmd):
        try:
            response = self._exchange(cmd)
        except Exception:
            logger.exception("Creality MCU command failed: %s", cmd)
            return False
        if not response.startswith("OK"):
            logger.error("Creality MCU rejected %s: %s", cmd, response)
            return False
        return True

    def move_motor(self, axis, distance):
        axis = axis.lower()
        if axis not in self._motor_status["positions"]:
            return False
        if not self._motor_status["homed"][axis]:
            logger.error("Refusing to move unhomed axis %s", axis.upper())
            return False
        next_position = self._motor_status["positions"][axis] + float(distance)
        if not self._position_min[axis] <= next_position <= self._position_max[axis]:
            logger.error(
                "Refusing %s move outside %.2f..%.2f mm",
                axis.upper(),
                self._position_min[axis],
                self._position_max[axis],
            )
            return False
        steps = round(float(distance) * self._steps_per_mm[axis])
        speed = self._move_speed_steps_s[axis]
        if not self._send_command(f"MOVE {axis.upper()} {steps} {speed}"):
            return False
        self._motor_status["positions"][axis] = next_position
        return True

    def home_motor(self, target):
        if target == "all":
            if not self._send_command("HOME ALL"):
                return False
            for ax in self._motor_status["positions"]:
                self._motor_status["positions"][ax] = 0.0
                self._motor_status["homed"][ax] = True
        else:
            ax = target.lower()
            if ax not in self._motor_status["positions"]:
                return False
            if not self._send_command(f"HOME {target.upper()}"):
                return False
            self._motor_status["positions"][ax] = 0.0
            self._motor_status["homed"][ax] = True
        return True

    def stop_motor(self, axis="all"):
        if axis == "all":
            if not self._send_command("STOP ALL"):
                return False
            for ax in self._motor_status["moving"]:
                self._motor_status["moving"][ax] = False
        else:
            ax = axis.lower()
            if ax not in self._motor_status["moving"]:
                return False
            if not self._send_command(f"STOP {axis.upper()}"):
                return False
            self._motor_status["moving"][ax] = False
        return True

    def get_motor_status(self):
        return copy.deepcopy(self._motor_status)

    def set_fan_speed(self, fan_name, speed):
        speed = max(0.0, min(1.0, float(speed)))
        pwm = int(speed * 255)

        if fan_name == "creality":
            success = self._send_command(f"FAN_PA0_PWM {pwm}")
            if success:
                self._fan_status["creality"] = speed
            return success

        if fan_name == "temperature":
            success = self._send_command(f"FAN_PA8_PWM {pwm}")
            if success:
                self._fan_status["temperature"] = speed
            return success

        raise ValueError(f"Unknown fan: {fan_name}")

    def get_fan_status(self):
        return dict(self._fan_status)

    def read_board_temperature(self):
        try:
            response = self._exchange("TEMP_PC5_READ")
        except Exception:
            logger.exception("Failed to read Creality PC5 temperature")
            return None

        match = _TEMPERATURE_RESPONSE.fullmatch(response)
        if match is None:
            logger.error("Invalid PC5 temperature response: %s", response)
            return None

        temperature = float(match.group(1))
        self._motor_status["temperature_c"] = temperature
        return temperature

    def read_temperature(self):
        return self.read_board_temperature()

    def close(self):
        if self._serial is None:
            return
        try:
            self._serial.close()
        finally:
            self._serial = None
