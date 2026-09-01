"""
Tests de compatibilité (PR #23) - GPIOLaserControl / USBDriver / ScannerApp

Ces tests valident les wrappers de compatibilité legacy qui délèguent aux
nouvelles classes (LaserController, USBScannerDriver) tout en conservant
l'API historique utilisée par les tests plus anciens et par ScannerApp.
"""

import unittest
from unittest.mock import MagicMock

from firmware.raspberry_pi.gpio_laser_control import GPIOLaserControl
from firmware.raspberry_pi.usb_driver import ScannerStatus, USBDriver
from firmware.raspberry_pi.scanner_app import ScannerApp


class FakeTransport:
    """Transport minimal qui renvoie toujours un statut OK."""

    def __init__(self):
        self.calls = []

    def exchange(self, payload: bytes) -> bytes:
        self.calls.append(payload)
        import struct

        head = struct.pack("<BBiiiB", 0, 0, 0, 0, 0, 0)
        checksum = 0
        for byte in head:
            checksum ^= byte
        return struct.pack("<BBiiiBB", 0, 0, 0, 0, 0, 0, checksum)


class TestGPIOLaserControlCompat(unittest.TestCase):
    """Wrapper GPIOLaserControl en mode simulation (use_board=False)."""

    def setUp(self):
        self.gpio = GPIOLaserControl(use_board=False)

    def test_simulation_mode_has_no_hardware(self):
        self.assertFalse(self.gpio.use_board)
        self.assertIsNone(self.gpio.laser_gauche)
        self.assertIsNone(self.gpio.laser_droit)

    def test_laser_on_off_are_noop_in_simulation(self):
        # Ne doit pas lever d'exception même sans backend GPIO réel.
        self.gpio.laser_on("both")
        self.gpio.laser_off("both")

    def test_laser_pulse_waits_without_hardware(self):
        # Doit patienter la durée demandée sans accéder au hardware.
        self.gpio.laser_pulse(1, side="left")

    def test_led_controls_are_noop(self):
        self.gpio.led_set_color(1.0, 0.0, 0.0)
        self.gpio.led_on("red")
        self.gpio.led_off()

    def test_fan_controls_are_noop(self):
        self.gpio.fan_on(0.5)
        self.gpio.fan_set_speed(0.8)
        self.gpio.fan_off()

    def test_status_helpers_are_noop(self):
        self.gpio.status_idle()
        self.gpio.status_ready()
        self.gpio.status_scanning()
        self.gpio.status_error()

    def test_shutdown_does_not_raise_without_controller(self):
        self.gpio.shutdown()

    def test_context_manager_shuts_down_on_exit(self):
        with GPIOLaserControl(use_board=False) as gpio:
            self.assertFalse(gpio.use_board)


class TestUSBDriverCompat(unittest.TestCase):
    """Wrapper USBDriver: simulation (sans transport) et délégation."""

    def test_connect_and_disconnect_return_true_in_simulation(self):
        driver = USBDriver()
        self.assertTrue(driver.connect())
        self.assertTrue(driver.disconnect())

    def test_move_and_home_return_true_without_transport(self):
        driver = USBDriver()
        self.assertTrue(driver.move("X", 100))
        self.assertTrue(driver.home("Y"))

    def test_move_delegates_to_transport_when_present(self):
        transport = FakeTransport()
        driver = USBDriver(transport)

        status = driver.move("x", 50, speed=10)

        self.assertIsInstance(status, ScannerStatus)
        self.assertEqual(transport.calls[0][0], 0x01)  # CMD_MOVE_X

    def test_home_delegates_to_transport_when_present(self):
        transport = FakeTransport()
        driver = USBDriver(transport)

        status = driver.home("z")

        self.assertIsInstance(status, ScannerStatus)
        self.assertEqual(transport.calls[0][0], 0x12)  # CMD_HOME_Z


class TestScannerAppControllerInjection(unittest.TestCase):
    """ScannerApp avec injection d'un controller (mode scan-sequence)."""

    def test_default_construction_uses_simulation_gpio(self):
        app = ScannerApp(use_gpio=False)
        self.assertFalse(app.gpio.use_board)

    def test_controller_injection_forces_simulation_gpio(self):
        controller = MagicMock()
        lasers = MagicMock()
        sensors = MagicMock()

        # use_gpio=True is ignored when a controller is injected: the
        # scan-sequence mode always runs the legacy GPIO wrapper in
        # simulation, since lasers are driven via the injected `lasers`.
        app = ScannerApp(controller=controller, lasers=lasers, sensors=sensors, use_gpio=True)

        self.assertFalse(app.gpio.use_board)
        self.assertIs(app._controller, controller)
        self.assertIs(app._lasers, lasers)
        self.assertIs(app._sensors, sensors)

    def test_run_scan_requires_controller_lasers_and_sensors(self):
        app = ScannerApp()
        with self.assertRaises(RuntimeError):
            app.run_scan(x_offsets=[0], z_offsets=[0], rotation_steps=1, step_per_rotation=10)

    def test_run_scan_uses_injected_controller_and_lasers(self):
        controller = MagicMock()
        lasers = MagicMock()
        sensors = MagicMock()
        sensors.capture.return_value = {"lidar": []}

        def fake_perform_scan_sequence(x_offsets, z_offsets, rotation_steps, step_per_rotation, on_capture):
            on_capture(MagicMock())

        controller.perform_scan_sequence.side_effect = fake_perform_scan_sequence

        app = ScannerApp(controller=controller, lasers=lasers, sensors=sensors)
        frames = app.run_scan(x_offsets=[0], z_offsets=[0], rotation_steps=1, step_per_rotation=10)

        self.assertEqual(len(frames), 1)
        lasers.enable_both.assert_called_once()
        lasers.disable_both.assert_called_once()


if __name__ == "__main__":
    unittest.main()
