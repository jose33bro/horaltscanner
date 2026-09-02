#!/usr/bin/env python3
"""Direct hardware diagnostic for HoralScanner (no web UI involved).

Run this script directly on the Raspberry Pi to check why the Pi camera
(CSI), the USB camera, or the GPIO (lasers/LED/fan) do not activate from
the web interface. It exercises the same drivers used by the Flask API
but prints a clear pass/fail report with the underlying error for each
component, so problems (missing packages, permissions, wrong device
index, ...) can be diagnosed without going through the browser.

Usage (from the repo root, ideally inside the project virtualenv):
    python3 software/scripts/diagnose_hardware.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SOFTWARE_DIR = _SCRIPT_DIR.parent
_REPO_ROOT = _SOFTWARE_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_SOFTWARE_DIR))

OK = "\033[32mOK\033[0m"
FAIL = "\033[31mECHEC\033[0m"


def _report(label: str, ok: bool, detail: str | None = None) -> None:
    print(f"[{OK if ok else FAIL}] {label}")
    if detail:
        print(f"       -> {detail}")


def check_pi_camera() -> None:
    from software.api.camera_driver import PiCamera, _PICAM_AVAILABLE

    if not _PICAM_AVAILABLE:
        _report(
            "Pi Camera (CSI) - module picamera2",
            False,
            "picamera2 non installe. sudo apt install -y python3-picamera2",
        )
        return

    camera = PiCamera()
    opened = camera.open()
    _report("Pi Camera (CSI) - ouverture", opened, camera.last_error)
    if opened:
        jpeg = camera.capture_jpeg()
        _report("Pi Camera (CSI) - capture d'image", jpeg is not None)
        camera.close()


def check_usb_camera() -> None:
    from software.api import config_manager
    from software.api.camera_driver import LogitechCamera, _CV2_AVAILABLE

    if not _CV2_AVAILABLE:
        _report(
            "Camera USB - module OpenCV (cv2)",
            False,
            "opencv-python non installe. pip install opencv-python",
        )
        return

    hardware_config = config_manager.load_hardware_config()
    device_id = hardware_config.get("cameras", {}).get("usb_device_id", "auto")
    camera = LogitechCamera(device_id=device_id)
    opened = camera.open()
    _report(f"Camera USB (device_id={device_id}) - ouverture", opened, camera.last_error)
    if opened:
        jpeg = camera.capture_jpeg()
        _report("Camera USB - capture d'image", jpeg is not None)
        camera.close()


def check_gpio() -> None:
    from software.api import config_manager
    from software.drivers.gpio_driver import GPIODriver

    hardware_config = config_manager.load_hardware_config()
    pi_gpio_enabled = bool(hardware_config.get("hardware", {}).get("pi_gpio", False))

    if not pi_gpio_enabled:
        _report(
            "GPIO - configuration",
            False,
            "hardware.pi_gpio est a false dans config/horalscanner_config.json "
            "(mode simulation force).",
        )
        return

    try:
        from gpiozero import OutputDevice, PWMOutputDevice

        def output_device_factory(pin, active_high=True, initial_value=False):
            return OutputDevice(pin, active_high=active_high, initial_value=bool(initial_value))

        def pwm_device_factory(pin, active_high=True, initial_value=False):
            return PWMOutputDevice(pin, active_high=active_high, initial_value=1.0 if initial_value else 0.0)
    except Exception as exc:
        _report(
            "GPIO - import gpiozero",
            False,
            f"{exc}. Verifiez que gpiozero et un pin factory (lgpio/RPi.GPIO) sont installes, "
            "et que l'utilisateur appartient au groupe 'gpio'.",
        )
        return

    driver = GPIODriver(
        simulation=False,
        hardware_config=hardware_config,
        output_device_factory=output_device_factory,
        pwm_device_factory=pwm_device_factory,
    )
    connected = driver.connect()
    _report("GPIO - connexion materielle", connected, str(driver.last_error) if driver.last_error else None)
    if connected:
        driver.close()


def check_stm32() -> None:
    from software.api import config_manager
    from software.drivers.stm32_driver import STM32Driver

    hardware_config = config_manager.load_hardware_config()
    stm32_enabled = bool(hardware_config.get("hardware", {}).get("mcu"))

    if not stm32_enabled:
        _report(
            "STM32 (Creality) - configuration",
            False,
            "hardware.mcu n'est pas defini dans config/horalscanner_config.json.",
        )
        return

    driver = STM32Driver(simulation=False, hardware_config=hardware_config)
    connected = driver.connect()
    _report("STM32 (Creality) - connexion serie", connected, str(driver.last_error) if driver.last_error else None)


def main() -> int:
    print("=== Diagnostic materiel HoralScanner (test direct, hors interface web) ===\n")
    check_pi_camera()
    print()
    check_usb_camera()
    print()
    check_gpio()
    print()
    check_stm32()
    print("\nTermine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
