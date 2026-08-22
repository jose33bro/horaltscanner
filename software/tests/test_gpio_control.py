"""
Tests GPIO Control - Tests unitaires pour la gestion GPIO
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path
import time

# Ajouter le chemin du firmware
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'firmware' / 'raspberry_pi'))

# Mock gpiozero avant l'import
with patch.dict('sys.modules', {'gpiozero': MagicMock(), 'gpiozero.pins': MagicMock(), 'gpiozero.pins.rpigpio': MagicMock()}):
    from gpio_laser_control import GPIOLaserControl


class TestGPIOLaserControl(unittest.TestCase):
    """Tests de la gestion GPIO"""

    def setUp(self):
        """Préparation avant chaque test"""
        # Tester en mode simulation (sans GPIO réel)
        self.gpio = GPIOLaserControl(use_board=False)

    def test_initialization_simulation(self):
        """Test initialisation en mode simulation"""
        self.assertFalse(self.gpio.use_board)
        self.assertIsNone(self.gpio.laser_gauche)
        self.assertIsNone(self.gpio.laser_droit)

    def test_laser_on_simulation(self):
        """Test allumage laser en simulation"""
        # Ne devrait pas lever d'exception
        self.gpio.laser_on("both")
        self.gpio.laser_on("gauche")
        self.gpio.laser_on("droit")

    def test_laser_off_simulation(self):
        """Test extinction laser en simulation"""
        self.gpio.laser_off("both")
        self.gpio.laser_off("gauche")
        self.gpio.laser_off("droit")

    def test_laser_pulse_simulation(self):
        """Test pulse laser en simulation"""
        start = time.time()
        self.gpio.laser_pulse(50, side="both")
        elapsed = time.time() - start
        # Devrait prendre ~50ms
        self.assertGreater(elapsed, 0.04)
        self.assertLess(elapsed, 0.15)

    def test_led_set_color_simulation(self):
        """Test définir couleur LED"""
        self.gpio.led_set_color(1.0, 0.5, 0.0)
        self.gpio.led_set_color(0.0, 0.0, 0.0)

    def test_led_on_simulation(self):
        """Test allumage LED"""
        for color in ["red", "green", "blue", "yellow", "cyan", "magenta", "white"]:
            self.gpio.led_on(color)

    def test_led_off_simulation(self):
        """Test extinction LED"""
        self.gpio.led_off()

    def test_led_pulse_simulation(self):
        """Test pulse LED"""
        start = time.time()
        self.gpio.led_pulse("blue", 50)
        elapsed = time.time() - start
        self.assertGreater(elapsed, 0.04)

    def test_fan_on_simulation(self):
        """Test allumage ventilateur"""
        self.gpio.fan_on(1.0)
        self.gpio.fan_on(0.5)
        self.gpio.fan_on(0.0)

    def test_fan_off_simulation(self):
        """Test extinction ventilateur"""
        self.gpio.fan_off()

    def test_fan_set_speed_simulation(self):
        """Test définir vitesse ventilateur"""
        self.gpio.fan_set_speed(0.75)

    def test_status_presets_simulation(self):
        """Test presets de statut"""
        self.gpio.status_idle()
        self.gpio.status_ready()
        self.gpio.status_scanning()
        self.gpio.status_error()

    def test_shutdown_simulation(self):
        """Test arrêt complet"""
        self.gpio.shutdown()

    def test_context_manager(self):
        """Test context manager"""
        with GPIOLaserControl(use_board=False) as gpio:
            self.assertIsNotNone(gpio)
            gpio.laser_on()
        # Après sortie, devrait être arrêté

    def test_color_clamping(self):
        """Test limitation des valeurs couleur"""
        # Les valeurs devraient être clampées à [0, 1]
        self.gpio.led_set_color(2.0, -0.5, 0.5)
        # Ne devrait pas lever d'exception

    def test_invalid_color(self):
        """Test couleur invalide"""
        # Ne devrait pas lever d'exception
        self.gpio.led_on("invalid_color")


if __name__ == '__main__':
    unittest.main()
