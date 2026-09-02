import os
import shlex
import shutil
import subprocess
import time
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
            "verify_system_camera_stack",
            "configure_gpio",
            "configure_serial_devices",
            "setup_python",
            "test_installation",
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

    def test_import_validation_precedes_unit_change_and_restart(self):
        repair = self.script.split("--repair)", 1)[1].split(";;", 1)[0]
        expected_order = (
            "verify_system_camera_stack",
            "setup_python",
            "test_installation",
            "configure_serial_devices",
            "install_service",
            "systemctl restart horalscanner",
        )
        offsets = [repair.index(step) for step in expected_order]
        self.assertEqual(offsets, sorted(offsets))

    def test_health_check_uses_bounded_readiness_polling(self):
        self.assertIn("HORALSCANNER_HEALTH_TIMEOUT_S:-45", self.script)
        self.assertIn("HORALSCANNER_HEALTH_INTERVAL_S:-2", self.script)
        health = self.script.split("non_motion_health_check() {", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertIn("wait_for_service_ready", health)

    def test_existing_venv_is_upgraded_with_system_site_packages(self):
        self.assertIn(
            '"$SYSTEM_PYTHON" -m venv --upgrade --system-site-packages "$VENV_DIR"',
            self.script,
        )
        self.assertIn(
            '"$SYSTEM_PYTHON" -m venv --system-site-packages "$VENV_DIR"',
            self.script,
        )
        self.assertIn("include-system-site-packages", self.script)
        self.assertIn(
            '"$SYSTEM_PYTHON" -c "import libcamera; from picamera2 import Picamera2"',
            self.script,
        )
        self.assertIn(
            '"$VENV_DIR/bin/python3" -c \'import sys\'',
            self.script,
        )


@unittest.skipUnless(
    os.name == "posix" and shutil.which("bash"),
    "isolated setup shell tests require bash",
)
class RaspberryPiRepairShellBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.scratch = ROOT / ".test-setup-pi"
        shutil.rmtree(self.scratch, ignore_errors=True)
        self.scratch.mkdir()

    def tearDown(self):
        shutil.rmtree(self.scratch, ignore_errors=True)

    def test_false_system_site_packages_venv_is_upgraded(self):
        venv = self.scratch / "venv"
        binary = venv / "bin" / "python3"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
        config = venv / "pyvenv.cfg"
        config.write_text("include-system-site-packages = false\n", encoding="utf-8")
        call_log = self.scratch / "python-call.txt"
        fake_python = self.scratch / "system-python"
        fake_python.write_text(
            "#!/bin/bash\n"
            'printf "%s\\n" "$*" >"$CALL_LOG"\n'
            "sed -i 's/include-system-site-packages = false/"
            "include-system-site-packages = true/' \"$FAKE_VENV/pyvenv.cfg\"\n",
            encoding="utf-8",
        )
        fake_python.chmod(0o755)
        command = (
            f"source {shlex.quote(str(ROOT / 'setup_pi.sh'))}; "
            f"VENV_DIR={shlex.quote(str(venv))}; "
            f"SYSTEM_PYTHON={shlex.quote(str(fake_python))}; "
            "ensure_system_site_packages_venv"
        )

        subprocess.run(
            ["bash", "-c", command],
            check=True,
            env={
                **os.environ,
                "CALL_LOG": str(call_log),
                "FAKE_VENV": str(venv),
            },
        )

        self.assertIn("include-system-site-packages = true", config.read_text())
        self.assertEqual(
            call_log.read_text(encoding="utf-8").strip(),
            f"-m venv --upgrade --system-site-packages {venv}",
        )

    def test_executable_looking_broken_venv_is_safely_recreated(self):
        venv = self.scratch / "broken-venv"
        binary = venv / "bin" / "python3"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/missing/os-python\n", encoding="utf-8")
        binary.chmod(0o755)
        (venv / "pyvenv.cfg").write_text(
            "include-system-site-packages = false\n",
            encoding="utf-8",
        )
        sentinel = venv / "stale-file"
        sentinel.write_text("stale", encoding="utf-8")
        call_log = self.scratch / "recreate-call.txt"
        fake_python = self.scratch / "recreate-python"
        fake_python.write_text(
            "#!/bin/bash\n"
            'printf "%s\\n" "$*" >"$CALL_LOG"\n'
            'mkdir -p "$FAKE_VENV/bin"\n'
            "printf '#!/bin/sh\\nexit 0\\n' >\"$FAKE_VENV/bin/python3\"\n"
            'chmod 755 "$FAKE_VENV/bin/python3"\n'
            "printf 'include-system-site-packages = true\\n' "
            '> "$FAKE_VENV/pyvenv.cfg"\n',
            encoding="utf-8",
        )
        fake_python.chmod(0o755)
        command = (
            f"source {shlex.quote(str(ROOT / 'setup_pi.sh'))}; "
            f"VENV_DIR={shlex.quote(str(venv))}; "
            f"SYSTEM_PYTHON={shlex.quote(str(fake_python))}; "
            "ensure_system_site_packages_venv"
        )

        subprocess.run(
            ["bash", "-c", command],
            check=True,
            env={
                **os.environ,
                "CALL_LOG": str(call_log),
                "FAKE_VENV": str(venv),
            },
        )

        self.assertFalse(sentinel.exists())
        self.assertEqual(
            call_log.read_text(encoding="utf-8").strip(),
            f"-m venv --system-site-packages {venv}",
        )
        self.assertIn(
            "include-system-site-packages = true",
            (venv / "pyvenv.cfg").read_text(encoding="utf-8"),
        )

    def test_import_failure_does_not_change_or_restart_service(self):
        call_log = self.scratch / "calls.txt"
        overrides = " ".join(
            f"{name}() {{ :; }};"
            for name in (
                "preflight_check",
                "ensure_pi_user",
                "update_system",
                "install_system_deps",
                "verify_system_camera_stack",
                "configure_gpio",
                "configure_persistent_state",
                "setup_python",
            )
        )
        command = (
            f"source {shlex.quote(str(ROOT / 'setup_pi.sh'))}; "
            f"INSTALL_DIR={shlex.quote(str(ROOT))}; "
            f"CALL_LOG={shlex.quote(str(call_log))}; "
            f"{overrides} "
            'test_installation() { return 1; }; '
            'configure_serial_devices() { echo serial >>"$CALL_LOG"; }; '
            'install_service() { echo install >>"$CALL_LOG"; }; '
            'systemctl() { echo systemctl >>"$CALL_LOG"; }; '
            "main --repair"
        )

        result = subprocess.run(["bash", "-c", command], check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(call_log.exists())

    def test_readiness_poll_succeeds_after_delayed_http_startup(self):
        call_log = self.scratch / "curl-calls.txt"
        command = (
            f"source {shlex.quote(str(ROOT / 'setup_pi.sh'))}; "
            "HORALSCANNER_HEALTH_TIMEOUT_S=5; "
            "HORALSCANNER_HEALTH_INTERVAL_S=1; "
            "CURL_CALLS=0; "
            'systemctl() { [ "$1" = "is-active" ] && echo active; }; '
            "sleep() { :; }; "
            'curl() { CURL_CALLS=$((CURL_CALLS + 1)); '
            '[ "$CURL_CALLS" -ge 3 ]; }; '
            "wait_for_service_ready; "
            f'printf "%s" "$CURL_CALLS" >{shlex.quote(str(call_log))}'
        )

        subprocess.run(["bash", "-c", command], check=True)

        self.assertEqual(call_log.read_text(encoding="utf-8"), "3")

    def test_readiness_poll_reports_real_timeout_and_journal_hint(self):
        command = (
            f"source {shlex.quote(str(ROOT / 'setup_pi.sh'))}; "
            "HORALSCANNER_HEALTH_TIMEOUT_S=1; "
            "HORALSCANNER_HEALTH_INTERVAL_S=1; "
            'systemctl() { if [ "$1" = "is-active" ]; then echo active; '
            'else echo "mock service status"; fi; }; '
            "curl() { return 1; }; "
            'journalctl() { echo "mock journal"; }; '
            "wait_for_service_ready"
        )
        started = time.monotonic()

        result = subprocess.run(
            ["bash", "-c", command],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn("readiness timed out after 1s", result.stdout)
        self.assertIn("sudo journalctl", result.stdout)
        self.assertIn("mock journal", result.stdout)


if __name__ == "__main__":
    unittest.main()
