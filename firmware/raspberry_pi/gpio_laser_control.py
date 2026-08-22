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
