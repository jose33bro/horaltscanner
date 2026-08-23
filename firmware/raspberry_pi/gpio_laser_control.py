from __future__ import annotations

import time
from typing import Protocol


class GPIOBackend(Protocol):
    def setup_output(self, pin: int) -> None:
        ...

    def write(self, pin: int, value: bool) -> None:
        ...


class RpiGPIOBackend:
    def __init__(self) -> None:
        try:
            import RPi.GPIO as gpio
        except ImportError as exc:  # pragma: no cover - hardware environment specific
            raise RuntimeError("RPi.GPIO is required for RpiGPIOBackend") from exc

        self._gpio = gpio
        self._gpio.setmode(gpio.BCM)

    def setup_output(self, pin: int) -> None:
        self._gpio.setup(pin, self._gpio.OUT)

    def write(self, pin: int, value: bool) -> None:
        self._gpio.output(pin, self._gpio.HIGH if value else self._gpio.LOW)


class LaserController:
    def __init__(self, backend: GPIOBackend, left_pin: int = 17, right_pin: int = 27):
        self._backend = backend
        self._left_pin = left_pin
        self._right_pin = right_pin
        self._backend.setup_output(left_pin)
        self._backend.setup_output(right_pin)

    def enable_left(self) -> None:
        self._backend.write(self._left_pin, True)

    def enable_right(self) -> None:
        self._backend.write(self._right_pin, True)

    def enable_both(self) -> None:
        self.enable_left()
        self.enable_right()

    def disable_both(self) -> None:
        self._backend.write(self._left_pin, False)
        self._backend.write(self._right_pin, False)

    def pulse_both(self, duration_s: float) -> None:
        self.enable_both()
        time.sleep(duration_s)
        self.disable_both()


class GPIOLaserControl:
    """Backward-compatible GPIO helper kept for the older unit tests."""

    def __init__(self, use_board: bool = True):
        self.use_board = use_board
        self.laser_gauche = None
        self.laser_droit = None
        self.led_color = (0.0, 0.0, 0.0)
        self.fan_speed = 0.0

    def laser_on(self, side: str = "both") -> None:
        return None

    def laser_off(self, side: str = "both") -> None:
        return None

    def laser_pulse(self, duration_ms: int, side: str = "both") -> None:
        self.laser_on(side)
        time.sleep(duration_ms / 1000.0)
        self.laser_off(side)

    def led_set_color(self, r: float, g: float, b: float) -> None:
        self.led_color = (
            max(0.0, min(1.0, r)),
            max(0.0, min(1.0, g)),
            max(0.0, min(1.0, b)),
        )

    def led_on(self, color: str = "white") -> None:
        presets = {
            "red": (1.0, 0.0, 0.0),
            "green": (0.0, 1.0, 0.0),
            "blue": (0.0, 0.0, 1.0),
            "yellow": (1.0, 1.0, 0.0),
            "cyan": (0.0, 1.0, 1.0),
            "magenta": (1.0, 0.0, 1.0),
            "white": (1.0, 1.0, 1.0),
        }
        self.led_set_color(*presets.get(color, (1.0, 1.0, 1.0)))

    def led_off(self) -> None:
        self.led_set_color(0.0, 0.0, 0.0)

    def led_pulse(self, color: str = "blue", duration_ms: int = 100) -> None:
        self.led_on(color)
        time.sleep(duration_ms / 1000.0)
        self.led_off()

    def fan_on(self, speed: float = 1.0) -> None:
        self.fan_speed = max(0.0, min(1.0, speed))

    def fan_off(self) -> None:
        self.fan_speed = 0.0

    def fan_set_speed(self, speed: float) -> None:
        self.fan_on(speed)

    def status_idle(self) -> None:
        self.led_off()

    def status_ready(self) -> None:
        self.led_on("green")

    def status_scanning(self) -> None:
        self.led_on("blue")

    def status_error(self) -> None:
        self.led_on("red")

    def shutdown(self) -> None:
        self.laser_off("both")
        self.led_off()
        self.fan_off()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
