import copy


class STM32Driver:
    def __init__(self):
        self._fan_status = {
            "creality": 0.0,
            "temperature": 0.0,
        }
        self._motor_status = {
            "positions": {"x": 0.0, "y": 0.0, "z": 0.0},
            "moving": {"x": False, "y": False, "z": False},
            "temperature_c": 0.0,
        }

    def connect(self):
        return True

    def _send_command(self, cmd):
        return True

    def move_motor(self, axis, distance):
        axis = axis.lower()
        if axis not in self._motor_status["positions"]:
            return False
        if not self._send_command(f"MOVE_{axis.upper()} {distance}"):
            return False
        self._motor_status["positions"][axis] += float(distance)
        return True

    def home_motor(self, target):
        if target == "all":
            if not self._send_command(f"HOME_{target.upper()}"):
                return False
            for ax in self._motor_status["positions"]:
                self._motor_status["positions"][ax] = 0.0
        else:
            ax = target.lower()
            if ax not in self._motor_status["positions"]:
                return False
            if not self._send_command(f"HOME_{target.upper()}"):
                return False
            self._motor_status["positions"][ax] = 0.0
        return True

    def stop_motor(self, axis="all"):
        if axis == "all":
            if not self._send_command(f"STOP_{axis.upper()}"):
                return False
            for ax in self._motor_status["moving"]:
                self._motor_status["moving"][ax] = False
        else:
            ax = axis.lower()
            if ax not in self._motor_status["moving"]:
                return False
            if not self._send_command(f"STOP_{axis.upper()}"):
                return False
            self._motor_status["moving"][ax] = False
        return True

    def get_motor_status(self):
        return copy.deepcopy(self._motor_status)

    def set_fan_speed(self, fan_name, speed):
        speed = max(0.0, min(1.0, float(speed)))
        pwm = int(speed * 255)

        if fan_name == "creality":
            self._fan_status["creality"] = speed
            return self._send_command(f"FAN_PA0_PWM {pwm}")

        if fan_name == "temperature":
            self._fan_status["temperature"] = speed
            return self._send_command(f"FAN_PA8_PWM {pwm}")

        raise ValueError(f"Unknown fan: {fan_name}")

    def get_fan_status(self):
        return dict(self._fan_status)

    def read_board_temperature(self):
        return 0.0

    def read_temperature(self):
        return self.read_board_temperature()
