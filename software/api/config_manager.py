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
        "simulation": False,
    },
    "slicer": {
        "layer_height": 0.2,
        "infill": 20,
        "support": False,
        "nozzle_temp": 200,
    },
    "moonraker": {
        "url": "http://192.168.1.40:7125",
        "api_key": "",
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
    """Load the hardware configuration describing pins, motors, and MCU transport."""
    return _load_json_config(HARDWARE_CONFIG_PATH)


def save(config: dict) -> None:
    """Save configuration to disk."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    logger.info("Config saved to %s", CONFIG_PATH)
