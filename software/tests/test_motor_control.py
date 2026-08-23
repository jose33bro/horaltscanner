"""
Tests Motor Control - Tests unitaires pour le contrôleur de moteurs
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# Ajouter le chemin du firmware
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'firmware' / 'raspberry_pi'))

from usb_driver import USBDriver
from motor_control import MotorController
from config import MOTORS, STEPS_PER_ROTATION


class TestMotorController(unittest.TestCase):
    """Tests du contrôleur de moteurs"""

    def setUp(self):
        """Préparation avant chaque test"""
        self.mock_usb = MagicMock(spec=USBDriver)
        self.controller = MotorController(self.mock_usb)

    def test_initialization(self):
        """Test initialisation"""
        self.assertFalse(self.controller.state['X']['homed'])
        self.assertFalse(self.controller.state['Y']['homed'])
        self.assertFalse(self.controller.state['Z']['homed'])
        self.assertEqual(self.controller.state['X']['position'], 0.0)

    def test_home_single_axis(self):
        """Test homing d'un axe"""
        self.mock_usb.home.return_value = True

        result = self.controller.home('X')
        self.assertTrue(result)
        self.assertTrue(self.controller.state['X']['homed'])
        self.mock_usb.home.assert_called_with('X')

    def test_home_all_axes(self):
        """Test homing de tous les axes"""
        self.mock_usb.home.return_value = True

        result = self.controller.home_all()
        self.assertTrue(result)
        self.assertTrue(self.controller.is_homed())
        self.assertEqual(self.mock_usb.home.call_count, 3)

    def test_home_axis_failure(self):
        """Test échec du homing"""
        self.mock_usb.home.return_value = False

        result = self.controller.home('Y')
        self.assertFalse(result)
        self.assertFalse(self.controller.state['Y']['homed'])

    def test_move_absolute(self):
        """Test mouvement absolu"""
        self.mock_usb.move.return_value = True
        self.controller.state['X']['position'] = 0.0

        result = self.controller.move_abs('X', 50.0)
        self.assertTrue(result)
        self.assertEqual(self.controller.state['X']['position'], 50.0)
        self.mock_usb.move.assert_called_once()

    def test_move_absolute_out_of_limits(self):
        """Test mouvement hors limites"""
        result = self.controller.move_abs('X', 500.0)  # Max X = 210mm
        self.assertFalse(result)
        self.mock_usb.move.assert_not_called()

    def test_move_relative(self):
        """Test mouvement relatif"""
        self.mock_usb.move.return_value = True
        self.controller.state['Z']['position'] = 50.0

        result = self.controller.move_rel('Z', 30.0)
        self.assertTrue(result)
        self.assertEqual(self.controller.state['Z']['position'], 80.0)

    def test_move_steps(self):
        """Test mouvement en steps"""
        self.mock_usb.move.return_value = True
        self.controller.state['Y']['position'] = 0.0

        result = self.controller.move_steps('Y', 100)
        self.assertTrue(result)
        # Position devrait avoir changé
        self.assertNotEqual(self.controller.state['Y']['position'], 0.0)
        self.mock_usb.move.assert_called_once()

    def test_mm_to_steps_conversion(self):
        """Test conversion mm vers steps"""
        steps = self.controller._mm_to_steps('X', 10.0)  # 10mm
        self.assertGreater(steps, 0)
        # Pour X: rotation_distance=40mm, microsteps=16, steps_per_rotation=200
        # steps_per_mm = (200 * 16) / 40 = 80
        # steps = 10 * 80 = 800
        self.assertEqual(steps, 800)

    def test_steps_to_mm_conversion(self):
        """Test conversion steps vers mm"""
        mm = self.controller._steps_to_mm('X', 800)  # 800 steps
        self.assertAlmostEqual(mm, 10.0, places=1)

    def test_is_homed_all(self):
        """Test vérification homing tous les axes"""
        self.assertFalse(self.controller.is_homed())

        self.controller.state['X']['homed'] = True
        self.controller.state['Y']['homed'] = True
        self.controller.state['Z']['homed'] = True

        self.assertTrue(self.controller.is_homed())

    def test_is_homed_single_axis(self):
        """Test vérification homing axe unique"""
        self.assertFalse(self.controller.is_homed('X'))
        self.controller.state['X']['homed'] = True
        self.assertTrue(self.controller.is_homed('X'))

    def test_invalid_axis(self):
        """Test action avec axe invalide"""
        result = self.controller.move_abs('W', 100)
        self.assertFalse(result)
        self.mock_usb.move.assert_not_called()


if __name__ == '__main__':
    unittest.main()
