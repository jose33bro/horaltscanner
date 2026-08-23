"""conftest.py - Configuration pytest et fixtures communes"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ajouter le chemin du firmware aux imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'firmware' / 'raspberry_pi'))


@pytest.fixture
def mock_usb_driver():
    """Fixture: USBDriver mockée"""
    with patch('usb_driver.serial.Serial'):
        from usb_driver import USBDriver
        driver = USBDriver(port="/dev/null")
        driver.ser = MagicMock()
        driver.connected = True
        return driver


@pytest.fixture
def mock_motor_controller(mock_usb_driver):
    """Fixture: MotorController avec USBDriver mockée"""
    from motor_control import MotorController
    controller = MotorController(mock_usb_driver)
    return controller


@pytest.fixture
def mock_gpio_control():
    """Fixture: GPIOLaserControl en mode simulation"""
    from gpio_laser_control import GPIOLaserControl
    return GPIOLaserControl(use_board=False)


@pytest.fixture
def mock_scanner_app(mock_usb_driver, mock_motor_controller, mock_gpio_control):
    """Fixture: ScannerApp complètement mockée"""
    with patch('scanner_app.USBDriver', return_value=mock_usb_driver), \
         patch('scanner_app.MotorController', return_value=mock_motor_controller), \
         patch('scanner_app.GPIOLaserControl', return_value=mock_gpio_control):
        from scanner_app import ScannerApp
        app = ScannerApp(use_gpio=False)
        return app
