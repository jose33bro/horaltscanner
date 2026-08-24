class STM32Driver:
    def __init__(self):
        self._fan_status = {
            "creality": 0.0,
            "temperature": 0.0,
        }

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

    def read_board_temperature(self):
        return 0.0

    def read_temperature(self):
        return self.read_board_temperature()
