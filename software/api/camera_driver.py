"""
Camera Driver - PiCam (DSI) + Logitech (USB) capture
"""

import base64
import io
import logging
import threading
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports – gracefully degrade when not on Pi hardware
# ---------------------------------------------------------------------------
try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    logger.warning("OpenCV not available; USB camera will return placeholder frames")

try:
    from picamera2 import Picamera2
    _PICAM_AVAILABLE = True
except ImportError:
    _PICAM_AVAILABLE = False
    logger.warning("picamera2 not available; PiCam will return placeholder frames")


# ---------------------------------------------------------------------------
# Placeholder (grey JPEG)
# ---------------------------------------------------------------------------
_PLACEHOLDER_JPEG: bytes | None = None


def _make_placeholder() -> bytes:
    global _PLACEHOLDER_JPEG
    if _PLACEHOLDER_JPEG is not None:
        return _PLACEHOLDER_JPEG
    try:
        from PIL import Image
        img = Image.new("RGB", (640, 480), color=(80, 80, 80))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        _PLACEHOLDER_JPEG = buf.getvalue()
    except ImportError:
        # Minimal valid 1×1 JPEG
        _PLACEHOLDER_JPEG = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c"
            b"\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c"
            b"\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1edL\x04\x02\x01\x01\x02"
            b"\x01\x02\x04\x03\x02\x02\x04\x0b\x08\x08\x0b\x0e\x0e\x0e\x0e\x0e\x0e"
            b"\x0e\x0e\x0e\x0e\x0e\x0e\x0e\x0e\x0e\xff\xc0\x00\x0b\x08\x00\x01\x00"
            b"\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01"
            b"\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07"
            b"\x08\x09\x0a\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03"
            b"\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06"
            b'\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n'
            b"\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWXYZ"
            b"cdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96"
            b"\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5"
            b"\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4"
            b"\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1"
            b"\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00"
            b"?\x00\xfb\xd0\x00\x00\xff\xd9"
        )
    return _PLACEHOLDER_JPEG


# ---------------------------------------------------------------------------
# Logitech USB Camera
# ---------------------------------------------------------------------------

class LogitechCamera:
    """Captures frames from a V4L2 USB camera (Logitech C270 etc.)."""

    def __init__(self, device_id: int = 0):
        self.device_id = device_id
        self._cap = None
        self._lock = threading.Lock()

    def open(self) -> bool:
        if not _CV2_AVAILABLE:
            return False
        with self._lock:
            self._cap = cv2.VideoCapture(self.device_id)
            if not self._cap.isOpened():
                self._cap = None
                return False
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            return True

    def close(self) -> None:
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def capture_jpeg(self) -> bytes:
        """Capture one frame and return JPEG bytes."""
        with self._lock:
            if not self.is_open:
                return _make_placeholder()
            ret, frame = self._cap.read()
            if not ret:
                return _make_placeholder()
            _, buf = cv2.imencode(".jpg", frame)
            return buf.tobytes()

    def capture_jpeg_b64(self) -> str:
        return base64.b64encode(self.capture_jpeg()).decode()

    def mjpeg_generator(self):
        """Yield MJPEG boundary chunks for streaming."""
        while self.is_open:
            jpeg = self.capture_jpeg()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            )
            time.sleep(1 / 15)


# ---------------------------------------------------------------------------
# PiCam (DSI / CSI via libcamera / picamera2)
# ---------------------------------------------------------------------------

class PiCamera:
    """Captures frames from the Raspberry Pi camera module."""

    def __init__(self):
        self._cam = None

    def open(self) -> bool:
        if not _PICAM_AVAILABLE:
            return False
        try:
            self._cam = Picamera2()
            config = self._cam.create_still_configuration(
                main={"size": (1920, 1080), "format": "RGB888"}
            )
            self._cam.configure(config)
            self._cam.start()
            return True
        except Exception as exc:
            logger.error("PiCam open failed: %s", exc)
            self._cam = None
            return False

    def close(self) -> None:
        if self._cam:
            try:
                self._cam.stop()
                self._cam.close()
            except Exception:
                pass
            self._cam = None

    @property
    def is_open(self) -> bool:
        return self._cam is not None

    def capture_jpeg(self) -> bytes:
        if not self.is_open:
            return _make_placeholder()
        try:
            import numpy as np
            from PIL import Image
            array = self._cam.capture_array()
            img = Image.fromarray(array)
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            return buf.getvalue()
        except Exception as exc:
            logger.error("PiCam capture failed: %s", exc)
            return _make_placeholder()

    def capture_jpeg_b64(self) -> str:
        return base64.b64encode(self.capture_jpeg()).decode()
