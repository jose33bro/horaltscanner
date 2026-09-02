"""
Camera Driver - PiCam (CSI) + Logitech (USB) capture
"""

import base64
import glob
import io
import logging
import math
import threading
import time
from pathlib import Path

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

    FRESH_FRAME_GRABS = 2

    #: Indices tried, in order, when the configured ``device_id`` fails to
    #: open or fails to deliver a frame.
    FALLBACK_DEVICE_IDS = (0, 1, 2, 3)

    #: Class-level cache of the last device index that successfully opened
    #: and delivered a frame. Shared across instances so that a subsequent
    #: camera open (e.g. after a restart) tries the known-good index first
    #: instead of re-probing every candidate, cutting USB init time roughly
    #: in half.
    _last_working_device_id: int | str | None = None

    def __init__(self, device_id: int | str | None = None):
        self.device_id = self._normalize_device_id(device_id)
        self._cap = None
        self._lock = threading.Lock()
        self.last_error: str | None = None

    @staticmethod
    def _normalize_device_id(device_id: int | str | None) -> int | None:
        if device_id is None:
            return None
        if isinstance(device_id, str):
            if device_id.strip().lower() in ("", "auto"):
                return None
            try:
                return int(device_id)
            except ValueError:
                logger.warning(
                    "Invalid USB camera device_id=%r; falling back to automatic detection",
                    device_id,
                )
                return None
        return int(device_id)

    def open(self) -> bool:
        if not _CV2_AVAILABLE:
            self.last_error = (
                "OpenCV (cv2) n'est pas installe. "
                "Installez-le avec: pip install opencv-python"
            )
            return False
        with self._lock:
            candidates = self._automatic_device_candidates()
            if self.device_id is not None:
                candidates = [self.device_id, *candidates]
            if LogitechCamera._last_working_device_id is not None:
                candidates = [LogitechCamera._last_working_device_id, *candidates]
            seen: set = set()
            tried: list = []
            for idx in candidates:
                if idx in seen:
                    continue
                seen.add(idx)
                tried.append(idx)

                cap = cv2.VideoCapture(idx)
                opened = cap.isOpened()
                ok = False
                if opened:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                    buffer_size_property = getattr(cv2, "CAP_PROP_BUFFERSIZE", None)
                    if buffer_size_property is not None:
                        cap.set(buffer_size_property, 1)
                    ok, _frame = cap.read()

                if opened and ok:
                    self._cap = cap
                    if idx != self.device_id:
                        logger.info(
                            "USB camera: configured device_id=%s failed, "
                            "falling back to working index %s",
                            self.device_id, idx,
                        )
                    else:
                        logger.info("USB camera: opened on device_id=%s", idx)
                    self.device_id = idx
                    self.last_error = None
                    LogitechCamera._last_working_device_id = idx
                    return True

                logger.warning(
                    "USB camera: failed to open index %s (opened=%s, read=%s)",
                    idx, opened, ok,
                )
                cap.release()

            self._cap = None
            self.last_error = (
                f"Aucune camera USB fonctionnelle trouvee parmi les index {tried}. "
                "Verifiez le branchement, les permissions /dev/video*, "
                "et qu'aucun autre processus n'utilise la camera."
            )
            logger.error(
                "USB camera: no working device found among candidates %s",
                tried,
            )
            return False

    @classmethod
    def _automatic_device_candidates(cls) -> list[int | str]:
        """Prefer stable Logitech V4L2 identities, then enumerate all video nodes."""
        candidates: list[int | str] = []
        by_id = sorted(glob.glob("/dev/v4l/by-id/*"))
        candidates.extend(
            path
            for path in by_id
            if any(token in path.lower() for token in ("logitech", "046d", "c270"))
            and "video-index0" in path.lower()
        )

        for name_path in sorted(glob.glob("/sys/class/video4linux/video*/name")):
            try:
                device_name = Path(name_path).read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if not any(
                token in device_name.lower()
                for token in ("logitech", "046d", "c270")
            ):
                continue
            suffix = Path(name_path).parent.name.removeprefix("video")
            if suffix.isdigit():
                candidates.append(int(suffix))

        for device_path in sorted(glob.glob("/dev/video[0-9]*")):
            suffix = Path(device_path).name.removeprefix("video")
            if suffix.isdigit():
                candidates.append(int(suffix))
        candidates.extend(cls.FALLBACK_DEVICE_IDS)
        return candidates

    def close(self) -> None:
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def capture_jpeg(self) -> bytes | None:
        """Discard a bounded queue prefix and return a freshly encoded frame."""
        with self._lock:
            if not self.is_open:
                return None
            grab = getattr(self._cap, "grab", None)
            for _ in range(self.FRESH_FRAME_GRABS):
                if callable(grab):
                    ok = grab()
                else:
                    ok, _discarded = self._cap.read()
                if not ok:
                    self.last_error = "USB camera failed while discarding a queued frame"
                    return None
            ret, frame = self._cap.read()
            if not ret:
                self.last_error = "USB camera failed to capture a fresh frame"
                return None
            encoded, buf = cv2.imencode(".jpg", frame)
            if not encoded:
                self.last_error = "USB camera failed to encode a fresh frame"
                return None
            self.last_error = None
            return buf.tobytes()

    def capture_jpeg_b64(self) -> str | None:
        jpeg = self.capture_jpeg()
        return base64.b64encode(jpeg).decode() if jpeg is not None else None

    def mjpeg_generator(self):
        """Yield MJPEG boundary chunks for streaming."""
        while self.is_open:
            jpeg = self.capture_jpeg()
            if jpeg is None:
                logger.error("USB camera stream capture failed")
                break
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            )
            time.sleep(1 / 15)


# ---------------------------------------------------------------------------
# PiCam (CSI via libcamera / picamera2)
# ---------------------------------------------------------------------------

class PiCamera:
    """Captures frames from the Raspberry Pi camera module."""

    LOCK_WAIT_SECONDS = 0.25

    def __init__(self):
        self._cam = None
        self._lock = threading.Lock()
        self.last_error: str | None = None

    def _acquire(self, operation: str) -> bool:
        if self._lock.acquire(timeout=self.LOCK_WAIT_SECONDS):
            return True
        self.last_error = f"Pi Camera occupee pendant {operation}; reessayez."
        logger.warning("PiCam %s skipped because another operation is active", operation)
        return False

    def open(self) -> bool:
        if not _PICAM_AVAILABLE:
            self.last_error = (
                "picamera2 n'est pas installe ou le module libcamera est indisponible. "
                "Installez-le avec: sudo apt install -y python3-picamera2"
            )
            return False
        if not self._acquire("l'ouverture"):
            return False
        try:
            self._cam = Picamera2()
            config = self._cam.create_still_configuration(
                main={"size": (1920, 1080), "format": "RGB888"}
            )
            self._cam.configure(config)
            self._cam.start()
            self.last_error = None
            return True
        except Exception as exc:
            logger.error("PiCam open failed: %s", exc)
            self.last_error = (
                f"Ouverture de la Pi Camera impossible: {exc}. "
                "Verifiez le cable CSI, que la camera est activee "
                "(raspi-config) et qu'aucun autre processus ne l'utilise."
            )
            self._cam = None
            return False
        finally:
            self._lock.release()

    def close(self) -> None:
        if not self._acquire("la fermeture"):
            return
        if self._cam:
            try:
                self._cam.stop()
                self._cam.close()
            except Exception as exc:
                logger.warning("PiCam close failed: %s", exc)
            self._cam = None
        self._lock.release()

    @property
    def is_open(self) -> bool:
        return self._cam is not None

    def capture_jpeg(self) -> bytes | None:
        if not self.is_open:
            return None
        if not self._acquire("la capture"):
            return None
        try:
            from PIL import Image
            array = self._cam.capture_array()
            # picamera2's "RGB888" configuration actually delivers pixels in
            # BGR memory order (a well-known libcamera/DRM naming quirk: see
            # https://github.com/raspberrypi/picamera2/issues/848). Reverse
            # the channel axis so the array is true RGB before handing it to
            # PIL, otherwise captured frames (and downstream red-channel
            # laser-line detection) have red/blue swapped.
            array = array[:, :, ::-1]
            img = Image.fromarray(array)
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            return buf.getvalue()
        except Exception as exc:
            logger.error("PiCam capture failed: %s", exc)
            self.last_error = f"Capture Pi Camera impossible: {exc}"
            return None
        finally:
            self._lock.release()

    def capture_jpeg_b64(self) -> str | None:
        jpeg = self.capture_jpeg()
        return base64.b64encode(jpeg).decode() if jpeg is not None else None


def analyze_laser_line(jpeg: bytes) -> dict:
    """Detect a laser line in a JPEG frame and compute its orientation.

    Convention
    ----------
    The laser line is expected to be roughly **vertical** in the image
    (i.e. running from top to bottom).  The returned angle is measured
    from the vertical axis (positive Y direction of the image):

      * 0°   → perfectly vertical line (no correction needed)
      * +N°  → line tilts clockwise  (top shifts right relative to bottom)
      * −N°  → line tilts counter-clockwise (top shifts left)

    Correction recommendation
    -------------------------
    ``correction_deg`` is the *signed* rotation that must be applied to
    the physical laser to bring it back to vertical:

      * correction_deg > 0  → rotate the laser to the **right**  (clockwise)
      * correction_deg < 0  → rotate the laser to the **left**   (counter-clockwise)

    The human-readable ``instruction`` string is in French, e.g.:
      "Tourner à droite de +1.2°"
    """
    if not _CV2_AVAILABLE:
        return {"analysis_available": False, "line_detected": False}

    try:
        import numpy as np

        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("JPEG decode failed")

        height, width = image.shape[:2]

        # Isolate the red channel – line lasers have strong red (or violet) output.
        # Taking the red channel gives the best contrast for both red and violet lasers.
        red_channel = image[:, :, 2]  # BGR → channel 2 is red

        # Threshold: keep only bright pixels in the red channel
        threshold = max(150, int(red_channel.max() * 0.6))
        _, binary = cv2.threshold(red_channel, threshold, 255, cv2.THRESH_BINARY)

        # Detect line segments with probabilistic Hough transform.
        # theta=pi/45 (4° resolution) is sufficient for a laser line and is
        # ~4x faster than the default pi/180 (1° resolution) since it tests
        # 45 angles instead of 180.
        lines = cv2.HoughLinesP(
            binary,
            rho=1,
            theta=math.pi / 45,
            threshold=50,
            minLineLength=height // 8,
            maxLineGap=height // 6,
        )

        if lines is None or len(lines) == 0:
            return {
                "analysis_available": True,
                "line_detected": False,
                "instruction": "Ligne laser non détectée. Vérifiez que le laser est allumé et visible.",
            }

        # Compute the angle of each segment from the vertical axis.
        # For a segment (x1,y1)→(x2,y2):
        #   dx = x2 - x1, dy = y2 - y1
        #   angle from vertical = atan2(dx, dy) converted to degrees
        # Segments pointing upward vs downward are equivalent; normalise to
        # dy >= 0 so that the angle lives in (−90°, +90°).
        # Each segment is weighted by its Euclidean length so that longer,
        # more reliable segments have proportionally more influence.
        weighted_sum = 0.0
        total_weight = 0.0
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx = float(x2 - x1)
            dy = float(y2 - y1)
            if dy < 0:  # flip so dy >= 0
                dx, dy = -dx, -dy
            length = math.hypot(dx, dy)
            angle = math.degrees(math.atan2(dx, dy if dy != 0 else 1e-9))
            weighted_sum += angle * length
            total_weight += length

        angle_deg = float(round(weighted_sum / total_weight, 1))

        # The correction is the opposite rotation: to go from angle_deg → 0°
        # the laser must rotate by −angle_deg.
        correction_deg = float(round(-angle_deg, 1))

        if abs(correction_deg) < 0.05:
            instruction = "Alignement correct. Aucune correction nécessaire."
        elif correction_deg > 0:
            instruction = f"Tourner à droite de +{correction_deg}°"
        else:
            instruction = f"Tourner à gauche de {correction_deg}°"

        return {
            "analysis_available": True,
            "line_detected": True,
            "angle_deg": angle_deg,
            "correction_deg": correction_deg,
            "instruction": instruction,
            "frame_width": width,
            "frame_height": height,
        }
    except Exception:
        logger.exception("Laser line analysis failed")
        return {"analysis_available": False, "line_detected": False}


def analyze_camera_frame(
    jpeg: bytes,
    checkerboard_sizes: tuple[tuple[int, int], ...] = ((12, 7), (11, 6), (9, 6)),
    max_analysis_width: int = 960,
) -> dict:
    """Measure image quality and detect a calibration checkerboard.

    Checkerboard detection runs on a bounded-size image, while reported image
    dimensions and checkerboard coordinates remain in the captured frame's
    coordinate system.
    """
    if not _CV2_AVAILABLE:
        return {"analysis_available": False}

    try:
        import numpy as np

        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("JPEG decode failed")
        frame_height, frame_width = image.shape[:2]
        analysis_image = image
        if max_analysis_width > 0 and frame_width > max_analysis_width:
            scale = max_analysis_width / frame_width
            analysis_size = (
                max_analysis_width,
                max(1, int(round(frame_height * scale))),
            )
            analysis_image = cv2.resize(
                image,
                analysis_size,
                interpolation=cv2.INTER_AREA,
            )
        gray = cv2.cvtColor(analysis_image, cv2.COLOR_BGR2GRAY)
        checkerboard_found = False
        checkerboard_size = None
        checkerboard_corners = None
        for candidate_size in checkerboard_sizes:
            found, corners = cv2.findChessboardCorners(gray, candidate_size)
            if found:
                checkerboard_found = True
                checkerboard_size = candidate_size
                checkerboard_corners = corners
                break

        analysis_height, analysis_width = gray.shape
        brightness = float(gray.mean())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        center_x = None
        center_y = None
        offset_x = None
        offset_y = None
        if checkerboard_corners is not None:
            points = checkerboard_corners.reshape(-1, 2)
            center_x = float(points[:, 0].mean()) * frame_width / analysis_width
            center_y = float(points[:, 1].mean()) * frame_height / analysis_height
            offset_x = center_x - ((frame_width - 1) / 2.0)
            offset_y = center_y - ((frame_height - 1) / 2.0)

        return {
            "analysis_available": True,
            "width": frame_width,
            "height": frame_height,
            "analysis_width": analysis_width,
            "analysis_height": analysis_height,
            "brightness": round(brightness, 1),
            "sharpness": round(sharpness, 1),
            "checkerboard_found": checkerboard_found,
            "checkerboard_columns": checkerboard_size[0] if checkerboard_size else None,
            "checkerboard_rows": checkerboard_size[1] if checkerboard_size else None,
            "checkerboard_center_x_px": round(center_x, 1) if center_x is not None else None,
            "checkerboard_center_y_px": round(center_y, 1) if center_y is not None else None,
            "center_offset_x_px": round(offset_x, 1) if offset_x is not None else None,
            "center_offset_y_px": round(offset_y, 1) if offset_y is not None else None,
        }
    except Exception:
        logger.exception("Camera frame analysis failed")
        return {"analysis_available": False}
