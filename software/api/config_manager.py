"""
Config Manager - Load/save horalscanner.json configuration
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "scanner": {
        "resolution": "1920x1080",
        "laser_power": 100,
        "lidar_offset_mm": 0,
        "capture_fps": 30,
        "simulation": True,
    },
    "slicer": {
        "layer_height": 0.2,
        "infill": 20,
        "support": False,
        "nozzle_temp": 200,
    },
    "system": {
        "log_level": "INFO",
        "port": 5000,
    },
}

# Config file path: repo_root/config/horalscanner.json
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = os.environ.get("HORALSCANNER_CONFIG", str(_REPO_ROOT / "config" / "horalscanner.json"))
HARDWARE_CONFIG_PATH = os.environ.get(
    "HORALSCANNER_HARDWARE_CONFIG",
    str(_REPO_ROOT / "config" / "horalscanner_config.json"),
)


def _default_calibration_state_path() -> str:
    configured = os.environ.get("HORALSCANNER_CALIBRATION_STATE")
    if configured:
        return configured
    system_state = Path("/var/lib/horalscanner")
    if os.name == "posix" and (
        (system_state.exists() and os.access(system_state, os.W_OK))
        or (hasattr(os, "geteuid") and os.geteuid() == 0)
    ):
        return str(system_state / "calibration.json")
    user_state = Path(
        os.environ.get(
            "XDG_STATE_HOME",
            os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "state")),
        )
    )
    return str(user_state / "horalscanner" / "calibration.json")


CALIBRATION_STATE_PATH = _default_calibration_state_path()


def _load_json_config(path: str) -> dict:
    """Load a JSON file from disk and return an empty mapping on failure."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("Config file not found at %s, using defaults", path)
        return {}
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in config file %s: %s", path, e)
        return {}


def load() -> dict:
    """Load configuration from disk, filling missing keys with defaults."""
    data = _load_json_config(CONFIG_PATH)

    # Deep-merge defaults
    result = {}
    for section, defaults in DEFAULT_CONFIG.items():
        result[section] = {**defaults, **data.get(section, {})}
    return result


def load_hardware_config() -> dict:
    """Load tracked hardware defaults with validated persistent calibration overlaid."""
    hardware = _load_json_config(HARDWARE_CONFIG_PATH)
    state_path = Path(CALIBRATION_STATE_PATH)
    state = _load_json_config(str(state_path)) if state_path.exists() else {}
    calibration = state.get("scan_calibration")
    if calibration is not None:
        if _calibration_is_valid(calibration):
            hardware["scan_calibration"] = calibration
        else:
            logger.error("Ignoring invalid runtime calibration at %s", state_path)
        return hardware

    legacy = hardware.get("scan_calibration")
    if legacy is not None and _calibration_is_valid(legacy):
        try:
            document = {"schema_version": 1, "scan_calibration": legacy}
            _atomic_json_write(state_path, document, overwrite=False)
            migration_backup = state_path.with_suffix(
                state_path.suffix + ".migration.bak"
            )
            _atomic_json_write(migration_backup, document, overwrite=False)
            logger.info("Migrated legacy calibration to %s", state_path)
        except (OSError, FileExistsError):
            logger.exception("Unable to migrate legacy calibration to %s", state_path)
    return hardware


def _calibration_is_valid(calibration: object) -> bool:
    try:
        from software.api.geometric_calibration import validate_calibration_payload

        validate_calibration_payload(calibration)
        return True
    except Exception:
        return False


def _atomic_json_write(path: Path, payload: dict, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".new")
    try:
        mode = "x" if not temporary.exists() else "w"
        with open(temporary, mode, encoding="utf-8") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o640)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        if not overwrite and path.exists():
            raise FileExistsError(path)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def save(config: dict) -> None:
    """Save configuration to disk."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    logger.info("Config saved to %s", CONFIG_PATH)
