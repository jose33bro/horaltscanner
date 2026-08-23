"""
Klipper/Moonraker integration for HoralScanner.
Sends G-code commands via serial and interacts with Moonraker REST API.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import requests
import serial

logger = logging.getLogger(__name__)

# Default serial settings from printer.cfg
DEFAULT_SERIAL = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
DEFAULT_BAUD = 115200

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "settings.json")


def load_settings() -> Dict[str, Any]:
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


class KlipperClient:
    """Serial G-code client for Klipper (direct connection)."""

    def __init__(self, port: str = DEFAULT_SERIAL, baud: int = DEFAULT_BAUD):
        self.port = port
        self.baud = baud
        self._ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._connected = False

    def connect(self) -> bool:
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=5)
            self._connected = True
            time.sleep(2)  # wait for firmware ready
            logger.info("Klipper serial connected: %s", self.port)
            return True
        except Exception as exc:
            logger.warning("Serial connect failed: %s", exc)
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def send_gcode(self, command: str, wait_ok: bool = True, timeout: float = 10.0) -> str:
        """Send a single G-code command; return response line(s)."""
        with self._lock:
            if not self._connected or self._ser is None:
                raise ConnectionError("Not connected to Klipper")
            cmd = (command.strip() + "\n").encode()
            self._ser.write(cmd)
            if not wait_ok:
                return ""
            deadline = time.time() + timeout
            lines: list[str] = []
            while time.time() < deadline:
                if self._ser.in_waiting:
                    line = self._ser.readline().decode(errors="replace").strip()
                    lines.append(line)
                    if line.startswith("ok") or line.lower().startswith("error"):
                        break
                else:
                    time.sleep(0.05)
            return "\n".join(lines)

    # ---- Convenience wrappers matching printer.cfg macros ----

    def home_all(self) -> str:
        return self.send_gcode("HOME_ALL")

    def home_axis(self, axis: str) -> str:
        return self.send_gcode(f"G28 {axis.upper()}")

    def move(self, axis: str, mm: float, speed_mm_min: int = 3000) -> str:
        cmds = [
            "G91",
            f"G1 {axis.upper()}{mm:.3f} F{speed_mm_min}",
            "G90",
        ]
        resp = ""
        for c in cmds:
            resp += self.send_gcode(c) + "\n"
        return resp.strip()

    def rotate_deg(self, degrees: float) -> str:
        return self.send_gcode(f"ROTATE_DEG DEG={degrees:.3f}")

    def laser_on(self, side: str) -> str:
        macro = "LASER_G_ON" if side == "left" else "LASER_D_ON"
        return self.send_gcode(macro)

    def laser_off(self, side: str) -> str:
        macro = "LASER_G_OFF" if side == "left" else "LASER_D_OFF"
        return self.send_gcode(macro)

    def set_rgb(self, r: int, g: int, b: int) -> str:
        r_pct = round(r / 255 * 100, 1)
        g_pct = round(g / 255 * 100, 1)
        b_pct = round(b / 255 * 100, 1)
        return self.send_gcode(f"RGB_COLOR R={r_pct} G={g_pct} B={b_pct}")

    def read_lidar(self) -> str:
        return self.send_gcode("READ_LIDAR")

    def lidar_up(self) -> str:
        return self.send_gcode("LIDAR_UP")

    def lidar_down(self) -> str:
        return self.send_gcode("LIDAR_DOWN")

    def lidar_calibrate(self) -> str:
        return self.send_gcode("LIDAR_CALIBRATE")

    def capture_picam(self) -> str:
        return self.send_gcode("CAPTURE_PICAM")

    def capture_logi(self) -> str:
        return self.send_gcode("CAPTURE_LOGI")

    def get_temperature(self) -> Dict[str, Any]:
        resp = self.send_gcode("M105")
        return {"raw": resp}


class MoonrakerClient:
    """HTTP client for Moonraker REST API (used to send jobs to GrandVoile)."""

    def __init__(self, base_url: str = "", api_token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_token:
            h["X-Api-Key"] = self.api_token
        return h

    def test_connection(self) -> Dict[str, Any]:
        try:
            r = requests.get(
                f"{self.base_url}/api/version",
                headers=self._headers(),
                timeout=5,
            )
            return {"ok": r.status_code == 200, "data": r.json()}
        except Exception as exc:
            logger.warning("Moonraker test connection failed: %s", exc)
            return {"ok": False, "error": "Connection failed"}

    def upload_gcode(self, filename: str, gcode_bytes: bytes) -> Dict[str, Any]:
        url = f"{self.base_url}/server/files/upload"
        files = {"file": (filename, gcode_bytes, "text/plain")}
        headers = {}
        if self.api_token:
            headers["X-Api-Key"] = self.api_token
        try:
            r = requests.post(url, files=files, headers=headers, timeout=30)
            return {"ok": r.status_code == 201, "data": r.json()}
        except Exception as exc:
            logger.warning("Moonraker upload failed: %s", exc)
            return {"ok": False, "error": "Upload failed"}

    def start_print(self, filename: str) -> Dict[str, Any]:
        try:
            r = requests.post(
                f"{self.base_url}/printer/print/start",
                json={"filename": filename},
                headers=self._headers(),
                timeout=10,
            )
            return {"ok": r.ok, "data": r.json()}
        except Exception as exc:
            logger.warning("Moonraker start_print failed: %s", exc)
            return {"ok": False, "error": "Start print failed"}

    def get_print_status(self) -> Dict[str, Any]:
        try:
            r = requests.get(
                f"{self.base_url}/printer/objects/query?print_stats",
                headers=self._headers(),
                timeout=5,
            )
            return {"ok": r.ok, "data": r.json()}
        except Exception as exc:
            logger.warning("Moonraker get_print_status failed: %s", exc)
            return {"ok": False, "error": "Status request failed"}
