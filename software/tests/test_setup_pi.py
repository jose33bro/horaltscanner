import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RaspberryPiRepairScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (ROOT / "setup_pi.sh").read_text(encoding="utf-8")

    def test_repair_mode_restores_dependencies_aliases_service_and_health(self):
        repair = self.script.split("--repair)", 1)[1].split(";;", 1)[0]
        for required in (
            "install_system_deps",
            "configure_gpio",
            "configure_serial_devices",
            "setup_python",
            "install_service",
            "non_motion_health_check",
        ):
            self.assertIn(required, repair)

    def test_service_uses_persistent_state_and_safe_restart_policy(self):
        self.assertIn("StateDirectory=horalscanner", self.script)
        self.assertIn(
            'Environment="HORALSCANNER_CALIBRATION_STATE=$CALIBRATION_FILE"',
            self.script,
        )
        self.assertIn("Restart=on-failure", self.script)

    def test_setup_never_removes_or_replaces_measured_calibration(self):
        self.assertNotIn('rm "$CALIBRATION_FILE"', self.script)
        self.assertNotIn('rm -f "$CALIBRATION_FILE"', self.script)
        self.assertNotIn('> "$CALIBRATION_FILE"', self.script)
        self.assertIn("Preserved measured calibration", self.script)


if __name__ == "__main__":
    unittest.main()
