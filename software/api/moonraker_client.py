"""
Moonraker Client - Send G-code files to Klipper/Moonraker (remote Pi)
"""

import logging
import requests

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 30


class MoonrakerClient:
    """HTTP client for Moonraker REST API."""

    def __init__(self, url: str = "", api_key: str = ""):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

    def test_connection(self) -> dict:
        """Test connection to Moonraker. Returns {ok, version, error}."""
        try:
            r = requests.get(
                f"{self.url}/api/version",
                headers=self._headers(),
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            r.raise_for_status()
            data = r.json()
            return {"ok": True, "version": data.get("result", {}).get("sw_version", "?"), "error": ""}
        except Exception as exc:
            return {"ok": False, "version": "", "error": "Connection failed"}

    def upload_and_print(self, gcode_bytes: bytes, filename: str) -> dict:
        """Upload G-code file and optionally start printing.  Returns {ok, error}."""
        try:
            files = {"file": (filename, gcode_bytes, "text/plain")}
            headers = {}
            if self.api_key:
                headers["X-Api-Key"] = self.api_key
            r = requests.post(
                f"{self.url}/server/files/upload",
                files=files,
                data={"print": "false"},
                headers=headers,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            r.raise_for_status()
            return {"ok": True, "error": "", "result": r.json()}
        except Exception as exc:
            logger.error("upload_and_print error: %s", exc)
            return {"ok": False, "error": "Upload failed", "result": {}}

    def get_printer_info(self) -> dict:
        """Get printer status."""
        try:
            r = requests.get(
                f"{self.url}/printer/info",
                headers=self._headers(),
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            r.raise_for_status()
            return r.json().get("result", {})
        except Exception as exc:
            logger.error("get_printer_info: %s", exc)
            return {}

    def list_files(self) -> list:
        """List G-code files on the printer."""
        try:
            r = requests.get(
                f"{self.url}/server/files/list",
                headers=self._headers(),
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            r.raise_for_status()
            return r.json().get("result", [])
        except Exception as exc:
            logger.error("list_files: %s", exc)
            return []
