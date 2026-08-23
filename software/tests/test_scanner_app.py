"""
Tests Scanner App - Tests d'intégration de l'application scanner
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, call
import sys
from pathlib import Path

# Ajouter les chemins
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'firmware' / 'raspberry_pi'))

from usb_driver import USBDriver
from motor_control import MotorController
from scanner_app import ScannerApp


class TestScannerApp(unittest.TestCase):
    """Tests d'intégration de l'application scanner"""

    def setUp(self):
        """Préparation avant chaque test"""
        with patch('scanner_app.USBDriver'), \
             patch('scanner_app.GPIOLaserControl'), \
             patch('scanner_app.MotorController'):
            self.app = ScannerApp(use_gpio=False)

    @patch('scanner_app.USBDriver')
    @patch('scanner_app.GPIOLaserControl')
    @patch('scanner_app.MotorController')
    def test_initialization_success(self, mock_motor, mock_gpio, mock_usb):
        """Test initialisation réussie"""
        mock_usb_instance = MagicMock()
        mock_usb.return_value = mock_usb_instance
        mock_usb_instance.connect.return_value = True

        mock_motor_instance = MagicMock()
        mock_motor.return_value = mock_motor_instance
        mock_motor_instance.home_all.return_value = True

        app = ScannerApp(use_gpio=False)
        result = app.initialize()

        self.assertTrue(result)
        self.assertTrue(app.running)
        mock_usb_instance.connect.assert_called_once()
        mock_motor_instance.home_all.assert_called_once()

    @patch('scanner_app.USBDriver')
    @patch('scanner_app.GPIOLaserControl')
    def test_initialization_usb_failure(self, mock_gpio, mock_usb):
        """Test initialisation avec échec USB"""
        mock_usb_instance = MagicMock()
        mock_usb.return_value = mock_usb_instance
        mock_usb_instance.connect.return_value = False

        app = ScannerApp(use_gpio=False)
        result = app.initialize()

        self.assertFalse(result)
        self.assertFalse(app.running)

    def test_move_to(self):
        """Test déplacement vers position"""
        self.app.running = True
        self.app.motors = MagicMock()
        self.app.motors.move_abs.return_value = True

        result = self.app.move_to(x=50, y=0, z=100)
        self.assertTrue(result)
        self.assertEqual(self.app.motors.move_abs.call_count, 3)

    def test_move_to_not_initialized(self):
        """Test mouvement sans initialisation"""
        self.app.running = False
        result = self.app.move_to(x=50)
        self.assertFalse(result)

    def test_laser_test(self):
        """Test laser"""
        self.app.gpio = MagicMock()
        self.app.laser_test(100)
        self.app.gpio.laser_pulse.assert_called_once()

    def test_led_test(self):
        """Test LED"""
        self.app.gpio = MagicMock()
        self.app.led_test()
        # led_on devrait être appelé plusieurs fois (une par couleur)
        self.assertGreater(self.app.gpio.led_on.call_count, 0)

    def test_fan_test(self):
        """Test ventilateur"""
        self.app.gpio = MagicMock()
        self.app.fan_test(1)
        self.app.gpio.fan_on.assert_called_once()
        self.app.gpio.fan_off.assert_called_once()

    def test_cancel_scan(self):
        """Test annulation scan"""
        self.app.scan_active = True
        self.app.cancel_scan()
        self.assertFalse(self.app.scan_active)

    def test_shutdown(self):
        """Test arrêt"""
        self.app.running = True
        self.app.motors = MagicMock()
        self.app.usb.connected = True
        self.app.usb.disconnect = MagicMock()
        self.app.gpio = MagicMock()

        self.app.shutdown()

        self.assertFalse(self.app.running)
        self.app.gpio.shutdown.assert_called_once()
        self.app.usb.disconnect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
