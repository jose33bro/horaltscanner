from __future__ import annotations

import logging
import time
from typing import Protocol

logger = logging.getLogger(__name__)


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


<<<<<<< HEAD
# ---------------------------------------------------------------------------
# GPIOLaserControl - higher-level controller used by the scanner application
# ---------------------------------------------------------------------------

_LED_COLOURS: dict[str, tuple[float, float, float]] = {
    "red":     (1.0,  0.0,  0.0),
    "green":   (0.0,  1.0,  0.0),
    "blue":    (0.0,  0.0,  1.0),
    "yellow":  (1.0,  1.0,  0.0),
    "cyan":    (0.0,  1.0,  1.0),
    "magenta": (1.0,  0.0,  1.0),
    "white":   (1.0,  1.0,  1.0),
}


class GPIOLaserControl:
    """High-level GPIO controller for lasers, RGB LED ring, and Pi fan.

    Parameters
    ----------
    use_board:
        When True, attempts real gpiozero/RPi.GPIO hardware init.
        When False (simulation), all operations are no-ops so the class
        can be used on non-Pi hardware for testing.
    left_pin:  BCM pin number for the left laser (default 27)
    right_pin: BCM pin number for the right laser (default 22)
    fan_pin:   BCM pin number for the Pi fan (default 23)
    led_r_pin: BCM pin number for RGB LED red channel (default 18)
    led_g_pin: BCM pin number for RGB LED green channel (default 13)
    led_b_pin: BCM pin number for RGB LED blue channel (default 19)
    """

    def __init__(
        self,
        use_board: bool = True,
        *,
        left_pin: int = 27,
        right_pin: int = 22,
        fan_pin: int = 23,
        led_r_pin: int = 18,
        led_g_pin: int = 13,
        led_b_pin: int = 19,
    ) -> None:
        self.use_board = use_board

        # Public attributes expected by legacy scanner code
        self.laser_gauche = None
        self.laser_droit = None
        self._fan = None

        self._left_pin = left_pin
        self._right_pin = right_pin
        self._fan_pin = fan_pin
        self._led_r_pin = led_r_pin
        self._led_g_pin = led_g_pin
        self._led_b_pin = led_b_pin

        if use_board:
            self._init_hardware()

    def _init_hardware(self) -> None:
        try:
            from gpiozero import LED, PWMLED
            self.laser_gauche = LED(self._left_pin)
            self.laser_droit  = LED(self._right_pin)
            self._fan = PWMLED(self._fan_pin)
            logger.info("GPIOLaserControl hardware initialised (BCM)")
        except Exception as exc:  # pragma: no cover - hardware environment specific
            logger.warning("GPIOLaserControl hardware init failed: %s", exc)
            self.use_board = False

    # ------------------------------------------------------------------
    # Laser helpers
    # ------------------------------------------------------------------

    def laser_on(self, side: str = "both") -> None:
        if not self.use_board:
            return
        if side in ("gauche", "left", "both"):
            self.laser_gauche and self.laser_gauche.on()
        if side in ("droit", "right", "both"):
            self.laser_droit and self.laser_droit.on()

    def laser_off(self, side: str = "both") -> None:
        if not self.use_board:
            return
        if side in ("gauche", "left", "both"):
            self.laser_gauche and self.laser_gauche.off()
        if side in ("droit", "right", "both"):
            self.laser_droit and self.laser_droit.off()

    def laser_pulse(self, duration_ms: int = 100, side: str = "both") -> None:
        self.laser_on(side)
        time.sleep(duration_ms / 1000.0)
        self.laser_off(side)

    # ------------------------------------------------------------------
    # LED helpers
    # ------------------------------------------------------------------

    def led_set_color(self, r: float, g: float, b: float) -> None:
        """Set LED colour with float values in 0.0–1.0 (clamped)."""
        _ = (
            max(0.0, min(1.0, r)),
            max(0.0, min(1.0, g)),
            max(0.0, min(1.0, b)),
        )
        # On real hardware, PWMLED per channel would be used here.

    def led_on(self, color: str = "white") -> None:
        r, g, b = _LED_COLOURS.get(color, (0.5, 0.5, 0.5))
        self.led_set_color(r, g, b)

    def led_off(self) -> None:
        self.led_set_color(0.0, 0.0, 0.0)

    def led_pulse(self, color: str = "white", duration_ms: int = 100) -> None:
        self.led_on(color)
        time.sleep(duration_ms / 1000.0)
        self.led_off()

    # ------------------------------------------------------------------
    # Fan helpers
    # ------------------------------------------------------------------

    def fan_on(self, speed: float = 1.0) -> None:
        if self._fan is not None:
            try:
                self._fan.value = max(0.0, min(1.0, speed))
            except Exception:
                pass

    def fan_off(self) -> None:
        if self._fan is not None:
            try:
                self._fan.off()
            except Exception:
                pass

    def fan_set_speed(self, speed: float) -> None:
        self.fan_on(speed)

    # ------------------------------------------------------------------
    # Status presets (RGB LED status indicators)
    # ------------------------------------------------------------------

    def status_idle(self) -> None:
        self.led_off()

    def status_ready(self) -> None:
        self.led_on("green")

    def status_scanning(self) -> None:
        self.led_on("blue")

    def status_error(self) -> None:
        self.led_on("red")

    # ------------------------------------------------------------------
    # Shutdown / context manager
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        self.laser_off("both")
        self.led_off()
        self.fan_off()
        if self.use_board:
            try:
                self.laser_gauche and self.laser_gauche.close()
                self.laser_droit  and self.laser_droit.close()
                self._fan and self._fan.close()
            except Exception:
                pass
        logger.info("GPIOLaserControl shutdown complete")
=======
class GPIOLaserControl:
    """Compatibility wrapper around LaserController for simulation and legacy tests."""

    def __init__(self, use_board: bool = True):
        self.use_board = use_board
        self.laser_gauche = None
        self.laser_droit = None
        self._controller = None

        if use_board:
            self._backend = RpiGPIOBackend()
            self._controller = LaserController(self._backend)

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
        if side in ("both", "gauche", "left"):
            self._controller._backend.write(self._controller._left_pin, False)
        if side in ("both", "droit", "right"):
            self._controller._backend.write(self._controller._right_pin, False)

    def laser_pulse(self, duration_ms: float, side: str = "both") -> None:
        if self._controller is not None:
            self._controller.pulse_both(duration_ms / 1000.0)
        else:
            time.sleep(duration_ms / 1000.0)

    def led_set_color(self, r: float, g: float, b: float) -> None:
        pass

    def led_on(self, color: str = "white") -> None:
        pass

    def led_off(self) -> None:
        pass

    def led_pulse(self, color: str, duration_ms: float) -> None:
        time.sleep(duration_ms / 1000.0)

    def fan_on(self, speed: float = 1.0) -> None:
        pass

    def fan_off(self) -> None:
        pass

    def fan_set_speed(self, speed: float) -> None:
        pass

    def status_idle(self) -> None:
        pass

    def status_ready(self) -> None:
        pass

    def status_scanning(self) -> None:
        pass

    def status_error(self) -> None:
        pass

    def shutdown(self) -> None:
        if self._controller is not None:
            self._controller.disable_both()
>>>>>>> origin/main

    def __enter__(self) -> "GPIOLaserControl":
        return self

<<<<<<< HEAD
    def __exit__(self, *args) -> None:
=======
    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
>>>>>>> origin/main
        self.shutdown()
