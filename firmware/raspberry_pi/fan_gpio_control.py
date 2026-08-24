from __future__ import annotations

import threading
import time
from typing import Callable, Optional


# Default thresholds (°C)
DEFAULT_FAN_ON_CELSIUS = 50.0
DEFAULT_FAN_OFF_CELSIUS = 45.0
DEFAULT_WARN_CELSIUS = 55.0
DEFAULT_EMERGENCY_CELSIUS = 60.0

# Default GPIO pin for the relay coil (BCM numbering)
DEFAULT_FAN_GPIO_PIN = 17


class FanGPIOController:
    """Controls a 24 V fan via a 5 V relay coil connected to a Raspberry Pi GPIO.

    Uses hysteresis to avoid rapid on/off switching:
      - Fan ON  when temperature > *fan_on_celsius*  (default 50 °C)
      - Fan OFF when temperature < *fan_off_celsius* (default 45 °C)

    An optional emergency callback is triggered when temperature exceeds
    *emergency_celsius* (default 60 °C).
    """

    def __init__(
        self,
        backend: "GPIOBackend",
        pin: int = DEFAULT_FAN_GPIO_PIN,
        fan_on_celsius: float = DEFAULT_FAN_ON_CELSIUS,
        fan_off_celsius: float = DEFAULT_FAN_OFF_CELSIUS,
        warn_celsius: float = DEFAULT_WARN_CELSIUS,
        emergency_celsius: float = DEFAULT_EMERGENCY_CELSIUS,
        on_emergency: Optional[Callable[[float], None]] = None,
    ) -> None:
        if fan_on_celsius <= fan_off_celsius:
            raise ValueError("fan_on_celsius must be greater than fan_off_celsius")
        self._backend = backend
        self._pin = pin
        self._fan_on_threshold = fan_on_celsius
        self._fan_off_threshold = fan_off_celsius
        self._warn_threshold = warn_celsius
        self._emergency_threshold = emergency_celsius
        self._on_emergency = on_emergency
        self._active = False
        self._lock = threading.Lock()

        self._backend.setup_output(pin)
        self._write_relay(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fan_on(self) -> None:
        """Force the fan relay ON regardless of temperature."""
        with self._lock:
            self._write_relay(True)

    def fan_off(self) -> None:
        """Force the fan relay OFF regardless of temperature."""
        with self._lock:
            self._write_relay(False)

    @property
    def is_on(self) -> bool:
        return self._active

    def set_thresholds(self, on_celsius: float, off_celsius: float) -> None:
        """Update hysteresis thresholds at runtime."""
        if on_celsius <= off_celsius:
            raise ValueError("on_celsius must be greater than off_celsius")
        with self._lock:
            self._fan_on_threshold = on_celsius
            self._fan_off_threshold = off_celsius

    def update(self, temperature_celsius: float) -> None:
        """Evaluate *temperature_celsius* and control the relay accordingly.

        Should be called regularly (e.g. every second) from a monitoring thread.
        Raises *OverheatError* if temperature exceeds the emergency threshold.
        """
        with self._lock:
            if temperature_celsius >= self._emergency_threshold:
                self._write_relay(False)
                if self._on_emergency is not None:
                    self._on_emergency(temperature_celsius)
                raise OverheatError(
                    f"Emergency stop: temperature {temperature_celsius:.1f} °C "
                    f">= {self._emergency_threshold:.1f} °C"
                )

            if not self._active and temperature_celsius > self._fan_on_threshold:
                self._write_relay(True)
            elif self._active and temperature_celsius < self._fan_off_threshold:
                self._write_relay(False)

    def start_monitoring(
        self,
        get_temperature: Callable[[], float],
        interval_s: float = 1.0,
    ) -> threading.Thread:
        """Start a daemon thread that calls *get_temperature* every *interval_s* seconds.

        Returns the thread so the caller can join it if needed.
        """
        thread = threading.Thread(
            target=self._monitor_loop,
            args=(get_temperature, interval_s),
            daemon=True,
            name="fan-monitor",
        )
        thread.start()
        return thread

    def _monitor_loop(self, get_temperature: Callable[[], float], interval_s: float) -> None:
        while True:
            try:
                temp = get_temperature()
                self.update(temp)
            except OverheatError:
                pass  # Emergency already handled via callback; keep looping
            except Exception:  # pragma: no cover - unexpected errors should not crash daemon
                pass
            time.sleep(interval_s)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_relay(self, state: bool) -> None:
        self._active = state
        self._backend.write(self._pin, state)


class OverheatError(RuntimeError):
    """Raised when the temperature exceeds the emergency threshold."""
