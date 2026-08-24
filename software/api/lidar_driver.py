"""
LIDAR Driver - TF-Luna serial communication
"""

import logging
import struct
import time

logger = logging.getLogger(__name__)

TFLUNA_BAUD = 115200
TFLUNA_FRAME_LEN = 9
TFLUNA_HEADER = b"\x59\x59"


class LidarDriver:
    """Driver for TF-Luna LIDAR over serial (USB-TTL)."""

    def __init__(self, port: str = "/dev/tfluna_usb_a1", baud: int = TFLUNA_BAUD):
        self.port = port
        self.baud = baud
        self._ser = None
        self._offset_mm: float = 0.0

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        try:
            import serial
            self._ser = serial.Serial(self.port, self.baud, timeout=0.5)
            logger.info("LIDAR connected on %s", self.port)
            return True
        except Exception as exc:
            logger.error("LIDAR connect failed: %s", exc)
            self._ser = None
            return False

    def disconnect(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def read_distance_mm(self) -> float | None:
        """Read one distance measurement.  Returns None on error."""
        if not self.connected:
            return None
        try:
            # TF-Luna outputs frames at up to 250 Hz; flush buffer first
            self._ser.reset_input_buffer()
            # Read until we find the 0x59 0x59 header
            for _ in range(50):
                byte = self._ser.read(1)
                if byte == b"\x59":
                    if self._ser.read(1) == b"\x59":
                        break
            else:
                return None
            rest = self._ser.read(TFLUNA_FRAME_LEN - 2)
            if len(rest) < TFLUNA_FRAME_LEN - 2:
                return None
            dist_low, dist_high = rest[0], rest[1]
            distance_cm = dist_low + (dist_high << 8)
            raw_mm = distance_cm * 10.0
            return raw_mm + self._offset_mm
        except Exception as exc:
            logger.error("LIDAR read error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def calibrate(self, known_distance_mm: float = 300.0, samples: int = 10) -> float:
        """Calibrate offset by measuring a known distance."""
        readings = []
        for _ in range(samples):
            d = self.read_distance_mm()
            if d is not None:
                readings.append(d)
            time.sleep(0.05)
        if not readings:
            logger.error("LIDAR calibration: no readings")
            return self._offset_mm
        measured = sum(readings) / len(readings)
        self._offset_mm = known_distance_mm - (measured - self._offset_mm)
        logger.info("LIDAR calibrated: offset=%.1f mm", self._offset_mm)
        return self._offset_mm

    def set_offset(self, offset_mm: float) -> None:
        self._offset_mm = offset_mm

    def get_offset(self) -> float:
        return self._offset_mm
