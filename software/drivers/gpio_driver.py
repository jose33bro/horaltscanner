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

        self._laser_status = {"left": False, "right": False}
        self._led_status = {"r": 0, "g": 0, "b": 0}
        self._fan_speed = 0.0

    def connect(self):
        return True

    def status(self):
        return {
            "simulation": self.simulation,
            "hardware_available": self.hardware_available,
            "pins": self._pins,
        }

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

    def led_set(self, r, g, b):
        self._led_status = {
            "r": max(0, min(255, int(r))),
            "g": max(0, min(255, int(g))),
            "b": max(0, min(255, int(b))),
        }
        return True

    def get_led_status(self):
        return dict(self._led_status)

    def set_fan_speed(self, speed):
        speed = max(0.0, min(1.0, float(speed)))
        self._fan_speed = speed
        return True

    def get_fan_status(self):
        return {"speed": self._fan_speed}

    def led_set_mode(self, mode):
        allowed = {"off", "white", "red", "green", "blue", "yellow", "cyan", "magenta"}
        if mode not in allowed:
            raise ValueError(f"Unknown LED mode: {mode}")
