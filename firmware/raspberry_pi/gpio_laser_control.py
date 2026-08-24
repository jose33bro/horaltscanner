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
    """Compatibility wrapper that exposes the legacy GPIO+LED+fan API while
    delegating laser control to :class:`LaserController` when hardware is
    available (``use_board=True``).  All methods are safe no-ops in
    simulation mode (``use_board=False``).
    """

    def __init__(self, use_board: bool = True) -> None:
        self.use_board = use_board
        self.laser_gauche = None
        self.laser_droit = None
        self._controller: LaserController | None = None

        if use_board:
            backend = RpiGPIOBackend()
            self._controller = LaserController(backend)

    # ------------------------------------------------------------------
    # Laser
    # ------------------------------------------------------------------

    def laser_on(self, side: str = "both") -> None:
        if self._controller is None:
            return
        if side in ("both", "gauche", "left"):
            self._controller.enable_left()
        if side in ("both", "droit", "right"):
            self._controller.enable_right()

    def laser_off(self, side: str = "both") -> None:
        if self._controller is None:
            return
        self._controller.disable_both()

    def laser_pulse(self, duration_ms: float, side: str = "both") -> None:
        self.laser_on(side)
        time.sleep(duration_ms / 1000.0)
        self.laser_off(side)

    # ------------------------------------------------------------------
    # LED (no dedicated hardware yet – simulation-safe stubs)
    # ------------------------------------------------------------------

    def led_set_color(self, r: float, g: float, b: float) -> None:
        pass

    def led_on(self, color: str = "white") -> None:
        pass

    def led_off(self) -> None:
        pass

    def led_pulse(self, color: str, duration_ms: float) -> None:
        time.sleep(duration_ms / 1000.0)

    # ------------------------------------------------------------------
    # Fan (no dedicated hardware yet – simulation-safe stubs)
    # ------------------------------------------------------------------

    def fan_on(self, speed: float = 1.0) -> None:
        pass

    def fan_off(self) -> None:
        pass

    def fan_set_speed(self, speed: float) -> None:
        pass

    # ------------------------------------------------------------------
    # Status presets (no dedicated hardware yet – simulation-safe stubs)
    # ------------------------------------------------------------------

    def status_idle(self) -> None:
        pass

    def status_ready(self) -> None:
        pass

    def status_scanning(self) -> None:
        pass

    def status_error(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        if self._controller is not None:
            self._controller.disable_both()

    def __enter__(self) -> "GPIOLaserControl":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.shutdown()
