import copy
import logging
from pathlib import Path
import threading
from typing import Any, Callable


logger = logging.getLogger(__name__)
_CPU_TEMPERATURE_PATH = Path("/sys/class/thermal/thermal_zone0/temp")


def _read_cpu_temperature() -> float:
    return float(_CPU_TEMPERATURE_PATH.read_text().strip()) / 1000.0


def _create_pwm_output_device(
    pin: int,
    frequency_hz: int,
    active_high: bool,
    initial_value: float,
):
    from gpiozero import PWMOutputDevice

    return PWMOutputDevice(
        pin,
        active_high=active_high,
        initial_value=initial_value,
        frequency=frequency_hz,
    )


def _create_output_device(pin: int, active_high: bool, initial_value: bool):
    from gpiozero import OutputDevice

    return OutputDevice(
        pin,
        active_high=active_high,
        initial_value=initial_value,
    )


class GPIODriver:
    def __init__(
        self,
        simulation=True,
        hardware_config=None,
        pwm_device_factory: Callable[[int, int, bool, float], Any] | None = None,
        output_device_factory: Callable[[int, bool, bool], Any] | None = None,
        temperature_reader: Callable[[], float] | None = None,
    ):
        self.simulation = simulation
        self.hardware_available = False
        hardware_config = hardware_config or {}

        lasers = hardware_config.get("lasers", {})
        led_rgb = hardware_config.get("led_rgb", {})
        fans = hardware_config.get("fans", {})
        pi_fan = fans.get("pi_fan", {})

        self._pins = {
            "laser_left": lasers.get("left", {}).get("gpio"),
            "laser_right": lasers.get("right", {}).get("gpio"),
            "led_r": led_rgb.get("red", {}).get("gpio"),
            "led_g": led_rgb.get("green", {}).get("gpio"),
            "led_b": led_rgb.get("blue", {}).get("gpio"),
            "fan_pi": pi_fan.get("gpio"),
        }
        self._pi_fan_active_high = bool(pi_fan.get("active_high", True))
        self._pi_fan_default_value = bool(pi_fan.get("default_value", False))
        self._pi_fan_auto_control = bool(pi_fan.get("auto_control", False))
        self._pi_fan_on_temp_c = float(pi_fan.get("on_temp_c", 55.0))
        self._pi_fan_off_temp_c = float(pi_fan.get("off_temp_c", 45.0))
        self._pi_fan_poll_interval_s = float(pi_fan.get("poll_interval_s", 5.0))
        if self._pi_fan_off_temp_c >= self._pi_fan_on_temp_c:
            raise ValueError("Pi fan off_temp_c must be lower than on_temp_c")
        self._led_frequency_hz = int(led_rgb.get("pwm_frequency_hz", 100))
        self._led_active_high = bool(led_rgb.get("active_high", True))
        self._laser_active_high = {
            "laser_left": bool(lasers.get("left", {}).get("active_high", True)),
            "laser_right": bool(lasers.get("right", {}).get("active_high", True)),
        }
        self._pwm_device_factory = pwm_device_factory or _create_pwm_output_device
        self._output_device_factory = output_device_factory or _create_output_device
        self._temperature_reader = temperature_reader or _read_cpu_temperature
        self._auto_stop_event = threading.Event()
        self._auto_thread = None
        self._devices = {}

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
        if self.simulation:
            return True

        if self.hardware_available:
            return True

        try:
            for name in ("laser_left", "laser_right"):
                pin = self._pins[name]
                if pin is not None:
                    self._devices[name] = self._output_device_factory(
                        int(pin),
                        self._laser_active_high[name],
                        False,
                    )

            for name in ("led_r", "led_g", "led_b"):
                pin = self._pins[name]
                if pin is not None:
                    self._devices[name] = self._pwm_device_factory(
                        int(pin),
                        self._led_frequency_hz,
                        self._led_active_high,
                        0.0,
                    )

            fan_pin = self._pins["fan_pi"]
            if fan_pin is not None:
                self._devices["fan_pi"] = self._output_device_factory(
                    int(fan_pin),
                    self._pi_fan_active_high,
                    self._pi_fan_default_value,
                )
        except Exception:
            logger.exception("Failed to initialize Raspberry Pi GPIO outputs")
            self.close()
            return False

        if not self._devices:
            logger.error("No Raspberry Pi GPIO outputs are configured")
            return False

        if "fan_pi" in self._devices:
            self._pi_fan_speed = 1.0 if self._pi_fan_default_value else 0.0
        self.hardware_available = True
        if self._pi_fan_auto_control and "fan_pi" in self._devices:
            self._start_pi_fan_auto_control()
        return True

    def _send_command(self, cmd):
        return True

    @staticmethod
    def _clamp_speed(speed):
        return max(0.0, min(1.0, float(speed)))

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
        if not self.simulation:
            device = self._devices.get(f"laser_{side}")
            if not self.hardware_available or device is None:
                logger.error("%s laser GPIO is unavailable", side.capitalize())
                return False
            try:
                device.on()
            except Exception:
                logger.exception("Failed to enable %s laser", side)
                return False
        self._laser_status[side] = True
        return True

    def laser_off(self, side):
        if side not in self._laser_status:
            return False
        if not self.simulation:
            device = self._devices.get(f"laser_{side}")
            if not self.hardware_available or device is None:
                logger.error("%s laser GPIO is unavailable", side.capitalize())
                return False
            try:
                device.off()
            except Exception:
                logger.exception("Failed to disable %s laser", side)
                return False
        self._laser_status[side] = False
        return True

    def get_laser_status(self):
        return dict(self._laser_status)

    # --- LED ---

    def led_set(self, r, g, b):
        values = {
            "r": max(0, min(255, int(r))),
            "g": max(0, min(255, int(g))),
            "b": max(0, min(255, int(b))),
        }
        if not self.simulation:
            if not self.hardware_available:
                logger.error("RGB LED GPIO is unavailable")
                return False
            try:
                for color, value in values.items():
                    device = self._devices.get(f"led_{color}")
                    if device is None:
                        logger.error("RGB LED %s GPIO is unavailable", color.upper())
                        return False
                    device.value = value / 255.0
            except Exception:
                logger.exception("Failed to set RGB LED")
                return False
        self._led_status = values
        return True

    def get_led_status(self):
        return dict(self._led_status)

    def led_set_mode(self, mode):
        colors = {
            "off": (0, 0, 0),
            "white": (255, 255, 255),
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255),
            "yellow": (255, 255, 0),
            "cyan": (0, 255, 255),
            "magenta": (255, 0, 255),
        }
        if mode not in colors:
            raise ValueError(f"Unknown LED mode: {mode}")
        return self.led_set(*colors[mode])

    # --- Pi fan ---

    def set_fan_speed(self, speed_or_fan, speed=None):
        """Set fan speed.

        Accepts two call signatures:
          set_fan_speed(1.0)               -> enables the Pi fan
          set_fan_speed(0.0)               -> disables the Pi fan
          set_fan_speed("creality", 0.5)   -> sets named STM32 fan speed
        """
        if speed is None:
            clamped = self._clamp_speed(speed_or_fan)
            enabled = clamped > 0.0
            if not self.simulation:
                fan_device = self._devices.get("fan_pi")
                if not self.hardware_available or fan_device is None:
                    logger.error("Pi fan GPIO is unavailable")
                    return False
                try:
                    fan_device.on() if enabled else fan_device.off()
                except Exception:
                    logger.exception("Failed to set Pi fan state")
                    return False
            self._pi_fan_speed = 1.0 if enabled else 0.0
            return True

        fan_name = speed_or_fan
        clamped = self._clamp_speed(speed)
        pwm = int(clamped * 255)
        if fan_name == "creality":
            self._fan_status["creality"] = clamped
            return self._send_command(f"FAN_PA0_PWM {pwm}")
        if fan_name == "temperature":
            self._fan_status["temperature"] = clamped
            return self._send_command(f"FAN_PA8_PWM {pwm}")
        raise ValueError(f"Unknown fan: {fan_name}")

    def get_fan_status(self):
        return {
            "speed": self._pi_fan_speed,
            "auto_control": self._pi_fan_auto_control,
            "cpu_temperature_c": self.read_pi_temperature(),
            "on_temp_c": self._pi_fan_on_temp_c,
            "off_temp_c": self._pi_fan_off_temp_c,
        }

    def read_pi_temperature(self):
        try:
            return round(float(self._temperature_reader()), 1)
        except (OSError, TypeError, ValueError):
            logger.exception("Failed to read Raspberry Pi CPU temperature")
            return None

    def update_pi_fan_auto_control(self):
        if not self._pi_fan_auto_control:
            return True

        temperature = self.read_pi_temperature()
        if temperature is None:
            logger.error("Enabling Pi fan because CPU temperature is unavailable")
            return self.set_fan_speed(1.0)
        if temperature >= self._pi_fan_on_temp_c:
            return self.set_fan_speed(1.0)
        if temperature <= self._pi_fan_off_temp_c:
            return self.set_fan_speed(0.0)
        return True

    def _start_pi_fan_auto_control(self):
        if self._auto_thread is not None and self._auto_thread.is_alive():
            return
        self._auto_stop_event.clear()
        self._auto_thread = threading.Thread(
            target=self._pi_fan_auto_loop,
            name="pi-fan-auto-control",
            daemon=True,
        )
        self._auto_thread.start()

    def _pi_fan_auto_loop(self):
        while not self._auto_stop_event.is_set():
            self.update_pi_fan_auto_control()
            self._auto_stop_event.wait(self._pi_fan_poll_interval_s)

    def close(self):
        self._auto_stop_event.set()
        if (
            self._auto_thread is not None
            and self._auto_thread.is_alive()
            and self._auto_thread is not threading.current_thread()
        ):
            self._auto_thread.join(timeout=self._pi_fan_poll_interval_s + 1.0)
        self._auto_thread = None
        for device in self._devices.values():
            try:
                device.close()
            except Exception:
                logger.exception("Failed to release a Raspberry Pi GPIO output")
        self._devices.clear()
        self._pi_fan_speed = 0.0
        self.hardware_available = False

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
