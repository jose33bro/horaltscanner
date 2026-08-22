"""
Tests USB Driver - Tests unitaires pour la communication STM32
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# Ajouter le chemin du firmware
sys.path.insert(0, str(Path(__file__).parent.parent / 'firmware' / 'raspberry_pi'))

from usb_driver import USBDriver, CommandStatus


class TestUSBDriver(unittest.TestCase):
    """Tests du driver USB"""

    def setUp(self):
        """Préparation avant chaque test"""
        self.driver = USBDriver(port="/dev/ttyUSB0", baudrate=115200)

    @patch('usb_driver.serial.Serial')
    def test_connect_success(self, mock_serial):
        """Test connexion réussie"""
        mock_ser = MagicMock()
        mock_serial.return_value = mock_ser
        mock_ser.readline.return_value = b"OK PONG\n"

        result = self.driver.connect()
        self.assertTrue(result)
        self.assertTrue(self.driver.connected)
        mock_serial.assert_called_once()

    @patch('usb_driver.serial.Serial')
    def test_connect_failure(self, mock_serial):
        """Test échec de connexion"""
        mock_serial.side_effect = Exception("Port not found")

        result = self.driver.connect()
        self.assertFalse(result)
        self.assertFalse(self.driver.connected)

    def test_parse_response_ok(self):
        """Test parsing réponse OK"""
        status, payload = self.driver._parse_response("OK MOVE")
        self.assertEqual(status, CommandStatus.SUCCESS)
        self.assertEqual(payload, "MOVE")

    def test_parse_response_error(self):
        """Test parsing réponse ERR"""
        status, payload = self.driver._parse_response("ERR AXIS")
        self.assertEqual(status, CommandStatus.ERROR)
        self.assertEqual(payload, "AXIS")

    def test_parse_response_empty(self):
        """Test parsing réponse vide"""
        status, payload = self.driver._parse_response("")
        self.assertEqual(status, CommandStatus.UNKNOWN)
        self.assertEqual(payload, "")

    def test_parse_response_complex(self):
        """Test parsing réponse complexe"""
        status, payload = self.driver._parse_response("OK X:0.00 Y:0.00 Z:0.00")
        self.assertEqual(status, CommandStatus.SUCCESS)
        self.assertIn("X:", payload)

    @patch.object(USBDriver, 'send_command')
    def test_ping(self, mock_send):
        """Test ping"""
        mock_send.return_value = "OK PONG"
        self.driver.connected = True

        result = self.driver.ping()
        self.assertTrue(result)
        mock_send.assert_called_with("PING")

    @patch.object(USBDriver, 'send_command')
    def test_move(self, mock_send):
        """Test mouvement moteur"""
        mock_send.return_value = "OK MOVE"
        self.driver.connected = True

        result = self.driver.move('X', 100, 50)
        self.assertTrue(result)
        mock_send.assert_called_with("MOVE X 100 50")

    @patch.object(USBDriver, 'send_command')
    def test_move_invalid_axis(self, mock_send):
        """Test mouvement avec axe invalide"""
        self.driver.connected = True
        result = self.driver.move('W', 100, 50)
        self.assertFalse(result)
        mock_send.assert_not_called()

    @patch.object(USBDriver, 'send_command')
    def test_home(self, mock_send):
        """Test homing"""
        mock_send.return_value = "OK HOME"
        self.driver.connected = True

        result = self.driver.home('Y')
        self.assertTrue(result)
        mock_send.assert_called_with("HOME Y")

    @patch.object(USBDriver, 'send_command')
    def test_get_endstop(self, mock_send):
        """Test lecture endstop"""
        mock_send.return_value = "OK ENDSTOP 1"
        self.driver.connected = True

        result = self.driver.get_endstop('X')
        self.assertTrue(result)

    @patch.object(USBDriver, 'send_command')
    def test_get_endstop_released(self, mock_send):
        """Test endstop non déclenché"""
        mock_send.return_value = "OK ENDSTOP 0"
        self.driver.connected = True

        result = self.driver.get_endstop('X')
        self.assertFalse(result)

    @patch.object(USBDriver, 'send_command')
    def test_sync(self, mock_send):
        """Test synchronisation"""
        mock_send.return_value = "OK SYNC TEST_TOKEN"
        self.driver.connected = True

        result = self.driver.sync("TEST_TOKEN")
        self.assertEqual(result, "TEST_TOKEN")

    @patch.object(USBDriver, 'send_command')
    def test_disconnect(self, mock_send):
        """Test déconnexion"""
        self.driver.ser = MagicMock()
        self.driver.ser.is_open = True
        self.driver.connected = True

        self.driver.disconnect()
        self.assertFalse(self.driver.connected)
        self.driver.ser.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
