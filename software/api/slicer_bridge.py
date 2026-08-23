"""
Slicer Bridge - PrusaSlicer CLI integration
"""

import base64
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Typical PrusaSlicer CLI binary names
_PRUSA_CANDIDATES = [
    "prusa-slicer",
    "prusa-slicer-console",
    "PrusaSlicer",
    "/usr/bin/prusa-slicer",
    "/opt/PrusaSlicer/prusa-slicer",
]


def _find_prusa_slicer() -> str | None:
    for candidate in _PRUSA_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    return None


class SlicerBridge:
    """Thin wrapper around the PrusaSlicer CLI."""

    def __init__(self, binary: str | None = None):
        self.binary = binary or _find_prusa_slicer()

    def is_available(self) -> bool:
        return self.binary is not None and os.path.isfile(self.binary)

    def slice_stl(
        self,
        stl_bytes: bytes,
        layer_height: float = 0.2,
        infill: int = 20,
        support: bool = False,
        nozzle_temp: int = 200,
    ) -> dict:
        """Slice an STL file and return {ok, gcode_b64, error}."""
        if not self.is_available():
            return {"ok": False, "gcode_b64": "", "error": "PrusaSlicer not found"}

        with tempfile.TemporaryDirectory(prefix="horalscanner_slice_") as tmpdir:
            stl_path = os.path.join(tmpdir, "model.stl")
            gcode_path = os.path.join(tmpdir, "model.gcode")

            with open(stl_path, "wb") as f:
                f.write(stl_bytes)

            cmd = [
                self.binary,
                "--export-gcode",
                stl_path,
                "--output", gcode_path,
                f"--layer-height={layer_height}",
                f"--fill-density={infill}%",
                f"--temperature={nozzle_temp}",
            ]
            if not support:
                cmd.append("--support-material=0")
            else:
                cmd.append("--support-material=1")

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    return {"ok": False, "gcode_b64": "", "error": result.stderr[:500]}

                with open(gcode_path, "rb") as f:
                    gcode_bytes = f.read()

                return {
                    "ok": True,
                    "gcode_b64": base64.b64encode(gcode_bytes).decode(),
                    "error": "",
                }
            except subprocess.TimeoutExpired:
                return {"ok": False, "gcode_b64": "", "error": "Slicer timeout"}
            except Exception as exc:
                return {"ok": False, "gcode_b64": "", "error": str(exc)}

    def get_version(self) -> str:
        if not self.is_available():
            return "not installed"
        try:
            result = subprocess.run(
                [self.binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() or result.stderr.strip()
        except Exception:
            return "unknown"
