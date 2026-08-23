"""
Camera driver for PiCam V3 NoIR (DSI) and Logitech C270 (USB).
Returns JPEG bytes or numpy frames.
"""

import io
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class LogitechCamera:
    """Logitech C270 USB camera via OpenCV."""

    def __init__(self, device_id: int = 0):
        self.device_id = device_id
        self._cap = None

    def open(self) -> bool:
        try:
            import cv2  # type: ignore
            self._cap = cv2.VideoCapture(self.device_id)
            if not self._cap.isOpened():
                logger.warning("Cannot open Logitech camera id=%s", self.device_id)
                self._cap = None
                return False
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            return True
        except Exception as exc:
            logger.warning("Logitech camera init error: %s", exc)
            return False

    def capture_jpeg(self) -> Optional[bytes]:
        try:
            import cv2  # type: ignore
            if self._cap is None:
                self.open()
            if self._cap is None:
                return None
            ret, frame = self._cap.read()
            if not ret:
                return None
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return buf.tobytes()
        except Exception as exc:
            logger.warning("Logitech capture failed: %s", exc)
            return None

    def capture_frame(self) -> Optional[np.ndarray]:
        try:
            import cv2  # type: ignore
            if self._cap is None:
                self.open()
            if self._cap is None:
                return None
            ret, frame = self._cap.read()
            return frame if ret else None
        except Exception as exc:
            logger.warning("Logitech capture frame failed: %s", exc)
            return None

    def release(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None


class PiCamera:
    """PiCam V3 NoIR via picamera2 library."""

    def __init__(self):
        self._cam = None

    def open(self) -> bool:
        try:
            from picamera2 import Picamera2  # type: ignore
            self._cam = Picamera2()
            config = self._cam.create_still_configuration(
                main={"size": (1920, 1080), "format": "RGB888"}
            )
            self._cam.configure(config)
            self._cam.start()
            return True
        except Exception as exc:
            logger.warning("PiCam init error: %s", exc)
            return False

    def capture_jpeg(self) -> Optional[bytes]:
        try:
            import cv2  # type: ignore
            frame = self.capture_frame()
            if frame is None:
                return None
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return buf.tobytes()
        except Exception as exc:
            logger.warning("PiCam capture failed: %s", exc)
            return None

    def capture_frame(self) -> Optional[np.ndarray]:
        try:
            import numpy as np  # type: ignore
            if self._cam is None:
                self.open()
            if self._cam is None:
                return None
            arr = self._cam.capture_array()
            return arr
        except Exception as exc:
            logger.warning("PiCam capture frame failed: %s", exc)
            return None

    def release(self) -> None:
        if self._cam:
            self._cam.stop()
            self._cam.close()
            self._cam = None
