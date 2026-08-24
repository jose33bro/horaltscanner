class STM32Driver:
    def __init__(self):
        self._fan_status = {
            "creality": 0.0,
            "temperature": 0.0,
        }
        self._motor_status = {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
            "moving": False,
        }

    def connect(self):
        return True

    def _send_command(self, cmd):
        return True

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

    def move_motor(self, axis, distance):
        axis = axis.lower()
        if axis not in ("x", "y", "z"):
            return False
        self._motor_status[axis] += float(distance)
        self._motor_status["moving"] = True
        self._motor_status["moving"] = False
        return True

    def home_motor(self, target):
        target = target.lower()
        if target == "all":
            for axis in ("x", "y", "z"):
                self._motor_status[axis] = 0.0
            return True
        if target in ("x", "y", "z"):
            self._motor_status[target] = 0.0
            return True
        return False

    def stop_motor(self, axis):
        self._motor_status["moving"] = False
        return True

    def get_motor_status(self):
        return dict(self._motor_status)

    def read_board_temperature(self):
        return 0.0

    def read_temperature(self):
        return self.read_board_temperature()

# Backward compatibility
GPIODriver = STM32Driver
