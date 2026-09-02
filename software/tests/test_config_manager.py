import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from software.api import config_manager


ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / ".test-config-manager"


class PersistentCalibrationConfigTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(exist_ok=True)
        self.hardware_path = SCRATCH / "hardware.json"
        self.state_path = SCRATCH / "state" / "calibration.json"
        self.hardware_path.write_text(
            json.dumps({"motors": {}, "scan_calibration": {"source": "tracked"}}),
            encoding="utf-8",
        )
        self.patchers = [
            mock.patch.object(
                config_manager, "HARDWARE_CONFIG_PATH", str(self.hardware_path)
            ),
            mock.patch.object(
                config_manager, "CALIBRATION_STATE_PATH", str(self.state_path)
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)

    def test_persistent_calibration_takes_precedence_over_tracked_defaults(self):
        runtime = {"source": "measured-runtime"}
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(
            json.dumps({"schema_version": 1, "scan_calibration": runtime}),
            encoding="utf-8",
        )

        with mock.patch.object(config_manager, "_calibration_is_valid", return_value=True):
            loaded = config_manager.load_hardware_config()

        self.assertEqual(loaded["scan_calibration"], runtime)
        self.assertEqual(
            json.loads(self.hardware_path.read_text())["scan_calibration"],
            {"source": "tracked"},
        )

    def test_valid_legacy_calibration_is_migrated_once_with_backup(self):
        with mock.patch.object(config_manager, "_calibration_is_valid", return_value=True):
            loaded = config_manager.load_hardware_config()

        self.assertEqual(loaded["scan_calibration"], {"source": "tracked"})
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["scan_calibration"], {"source": "tracked"})
        migration_backup = self.state_path.with_suffix(".json.migration.bak")
        self.assertEqual(
            json.loads(migration_backup.read_text(encoding="utf-8")), state
        )

        first_bytes = self.state_path.read_bytes()
        self.hardware_path.write_text(
            json.dumps({"scan_calibration": {"source": "new-tracked"}}),
            encoding="utf-8",
        )
        with mock.patch.object(config_manager, "_calibration_is_valid", return_value=True):
            loaded = config_manager.load_hardware_config()
        self.assertEqual(loaded["scan_calibration"], {"source": "tracked"})
        self.assertEqual(self.state_path.read_bytes(), first_bytes)

    def test_existing_invalid_runtime_file_is_never_overwritten_by_migration(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(
            json.dumps({"scan_calibration": {"invalid": True}}),
            encoding="utf-8",
        )
        before = self.state_path.read_bytes()

        with mock.patch.object(config_manager, "_calibration_is_valid", return_value=False):
            loaded = config_manager.load_hardware_config()

        self.assertEqual(loaded["scan_calibration"], {"source": "tracked"})
        self.assertEqual(self.state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
