import copy


class GPIODriver:
    def __init__(self, simulation=True, hardware_config=None):
        self.simulation = simulation
        self.hardware_available = False
        hardware_config = hardware_config or {}

        lasers = hardware_config.get("lasers", {})
        led_rgb = hardware_config.get("led_rgb", {})
        fans = hardware_config.get("fans", {})

        self._pins = {
            "laser_left": lasers.get("left", {}).get("gpio"),
            "laser_right": lasers.get("right", {}).get("gpio"),
            "led_r": led_rgb.get("red", {}).get("gpio"),
            "led_g": led_rgb.get("green", {}).get("gpio"),
            "led_b": led_rgb.get("blue", {}).get("gpio"),
            "fan_pi": fans.get("pi_fan", {}).get("gpio"),
        }

        self._fan_status = {
            "creality": 0.0,
            "temperature": 0.0,
        }
        self._motor_status = {
            "positions": {"x": 0.0, "y": 0.0, "z": 0.0},
            "moving": {"x": False, "y": False, "z": False},
            "temperature_c": 0.0,
        }
        self._laser_status = {"left": False, "right": False}
        self._led_status = {"r": 0, "g": 0, "b": 0}
        self._pi_fan_speed = 0.0

    def connect(self):
        return True

    def _send_command(self, cmd):
        return True

    def status(self):
        return {
            "simulation": self.simulation,
            "hardware_available": self.hardware_available,
            "pins": self._pins,
        }

    # --- Laser ---

    def laser_on(self, side):
        if side not in self._laser_status:
            return False
        self._laser_status[side] = True
        return True

    def laser_off(self, side):
        if side not in self._laser_status:
            return False
        self._laser_status[side] = False
        return True

    def get_laser_status(self):
        return dict(self._laser_status)

    # --- LED ---

    def led_set(self, r, g, b):
        self._led_status = {
            "r": max(0, min(255, int(r))),
            "g": max(0, min(255, int(g))),
            "b": max(0, min(255, int(b))),
        }
        return True

    def get_led_status(self):
        return dict(self._led_status)

    def led_set_mode(self, mode):
        allowed = {"off", "white", "red", "green", "blue", "yellow", "cyan", "magenta"}
        if mode not in allowed:
            raise ValueError(f"Unknown LED mode: {mode}")

    # --- Pi fan ---

    def set_fan_speed(self, speed_or_fan, speed=None):
        """Set fan speed.

        Accepts two call signatures:
          set_fan_speed(0.5)               -> sets Pi fan speed (0.0-1.0)
          set_fan_speed("creality", 0.5)   -> sets named STM32 fan speed
        """
        if speed is None:
            # Called as set_fan_speed(speed) — Pi fan
            clamped = max(0.0, min(1.0, float(speed_or_fan)))
            self._pi_fan_speed = clamped
            return True
        # Called as set_fan_speed(fan_name, speed) — STM32 fan
        fan_name = speed_or_fan
        clamped = max(0.0, min(1.0, float(speed)))
        pwm = int(clamped * 255)
        if fan_name == "creality":
            self._fan_status["creality"] = clamped
            return self._send_command(f"FAN_PA0_PWM {pwm}")
        if fan_name == "temperature":
            self._fan_status["temperature"] = clamped
            return self._send_command(f"FAN_PA8_PWM {pwm}")
        raise ValueError(f"Unknown fan: {fan_name}")

    def get_fan_status(self):
        return {"speed": self._pi_fan_speed}

    # --- Motors ---

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

    # --- Temperature ---

    def read_board_temperature(self):
        return 0.0

    def read_temperature(self):
        return self.read_board_temperature()


# Backward compatibility
STM32Driver = GPIODriver
