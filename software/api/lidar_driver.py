"""
TF-Luna LIDAR driver over USB serial.
Reads distance in cm and converts to mm.
"""

import logging
import struct
import threading
from typing import Optional

import serial

logger = logging.getLogger(__name__)

TF_LUNA_BAUD = 115200
TF_LUNA_FRAME_SIZE = 9
TF_LUNA_HEADER = 0x59


class LidarDriver:
    """TF-Luna LIDAR reader (binary protocol)."""

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = TF_LUNA_BAUD):
        self.port = port
        self.baud = baud
        self._ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._last_mm: Optional[float] = None

    def open(self) -> bool:
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=1)
            logger.info("LIDAR connected: %s", self.port)
            return True
        except Exception as exc:
            logger.warning("LIDAR connect failed: %s", exc)
            return False

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()

    def read_distance_mm(self) -> Optional[float]:
        """Return distance in mm, or None on error."""
        with self._lock:
            if self._ser is None:
                if not self.open():
                    return None
            try:
                # Sync to frame start (two 0x59 bytes)
                found = 0
                for _ in range(64):
                    b = self._ser.read(1)
                    if len(b) == 0:
                        return None
                    if b[0] == TF_LUNA_HEADER:
                        found += 1
                        if found == 2:
                            break
                    else:
                        found = 0
                else:
                    return None

                # Read remaining 7 bytes
                rest = self._ser.read(7)
                if len(rest) < 7:
                    return None

                dist_cm = struct.unpack_from("<H", rest, 0)[0]
                dist_mm = dist_cm * 10.0
                self._last_mm = dist_mm
                return dist_mm
            except Exception as exc:
                logger.warning("LIDAR read error: %s", exc)
                return None

    @property
    def last_mm(self) -> Optional[float]:
        return self._last_mm
