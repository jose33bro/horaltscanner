"""
Config Manager - Load/save horalscanner.json configuration
"""

import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "scanner": {
        "resolution": "1920x1080",
        "laser_power": 100,
        "lidar_offset_mm": 0,
        "capture_fps": 30,
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


def load() -> dict:
    """Load configuration from disk, filling missing keys with defaults."""
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning("Config file not found at %s, using defaults", CONFIG_PATH)
        data = {}
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in config file: %s", e)
        data = {}

    # Deep-merge defaults
    result = {}
    for section, defaults in DEFAULT_CONFIG.items():
        result[section] = {**defaults, **data.get(section, {})}
    return result


def save(config: dict) -> None:
    """Save configuration to disk."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    logger.info("Config saved to %s", CONFIG_PATH)
