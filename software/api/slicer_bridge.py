"""
PrusaSlicer CLI bridge.
Slices STL/AMF files and returns G-code bytes.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Common PrusaSlicer CLI binary names
PRUSA_CLI_CANDIDATES = [
    "prusa-slicer",
    "prusaslicer",
    "PrusaSlicer",
    "/usr/bin/prusa-slicer",
    "/opt/prusa-slicer/bin/prusa-slicer",
]

DEFAULT_PROFILE = {
    "layer_height": 0.2,
    "infill_density": 20,
    "support_material": False,
    "nozzle_diameter": 0.4,
    "filament_type": "PLA",
    "temperature": 215,
    "bed_temperature": 60,
    "perimeters": 3,
}


def find_prusa_cli() -> Optional[str]:
    for candidate in PRUSA_CLI_CANDIDATES:
        path = shutil.which(candidate) or (candidate if os.path.isfile(candidate) else None)
        if path:
            return path
    return None


class SlicerBridge:
    """Interface to PrusaSlicer CLI."""

    def __init__(self, cli_path: Optional[str] = None):
        self.cli_path = cli_path or find_prusa_cli()

    def available(self) -> bool:
        return self.cli_path is not None

    def slice_model(
        self,
        model_bytes: bytes,
        model_ext: str = "stl",
        profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Slice a 3D model.
        Returns {"ok": bool, "gcode": bytes|None, "log": str}.
        """
        if not self.available():
            return {"ok": False, "gcode": None, "log": "PrusaSlicer CLI not found"}

        # Select filename from fixed string literals based on validated extension
        if (model_ext or "").lower() == "amf":
            model_filename = "model.amf"
        else:
            model_filename = "model.stl"

        p = {**DEFAULT_PROFILE, **(profile or {})}

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, model_filename)
            gcode_path = os.path.join(tmpdir, "output.gcode")

            with open(model_path, "wb") as f:
                f.write(model_bytes)

            cmd: List[str] = [
                self.cli_path,
                "--slice",
                "--output", gcode_path,
                "--layer-height", str(p["layer_height"]),
                "--fill-density", f"{p['infill_density']}%",
                "--nozzle-diameter", str(p["nozzle_diameter"]),
                "--temperature", str(p["temperature"]),
                "--bed-temperature", str(p["bed_temperature"]),
                "--perimeters", str(p["perimeters"]),
            ]
            if p["support_material"]:
                cmd.append("--support-material")
            cmd.append(model_path)

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                log = result.stdout + result.stderr
                if result.returncode != 0:
                    return {"ok": False, "gcode": None, "log": log}
                if not os.path.exists(gcode_path):
                    return {"ok": False, "gcode": None, "log": "G-code output not found\n" + log}
                with open(gcode_path, "rb") as f:
                    gcode = f.read()
                return {"ok": True, "gcode": gcode, "log": log}
            except subprocess.TimeoutExpired:
                return {"ok": False, "gcode": None, "log": "PrusaSlicer timed out"}
            except Exception as exc:
                return {"ok": False, "gcode": None, "log": str(exc)}

    def get_version(self) -> str:
        if not self.available():
            return "not installed"
        try:
            r = subprocess.run([self.cli_path, "--version"], capture_output=True, text=True, timeout=5)
            return r.stdout.strip() or r.stderr.strip()
        except Exception as exc:
            return str(exc)
