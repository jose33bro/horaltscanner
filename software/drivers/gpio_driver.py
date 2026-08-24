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

    def status(self):
        return {
            "simulation": self.simulation,
            "hardware_available": self.hardware_available,
            "pins": self._pins,
        }

    def led_set_mode(self, mode):
        allowed = {"off", "white", "red", "green", "blue", "yellow", "cyan", "magenta"}
        if mode not in allowed:
            raise ValueError(f"Unknown LED mode: {mode}")
