from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LaserController:
    left_gpio_pin: int
    right_gpio_pin: int

    def set_state(self, left_on: bool, right_on: bool) -> None:
        # Le pilotage GPIO réel (RPi.GPIO ou gpiozero) est branché ici.
        _ = (left_on, right_on, self.left_gpio_pin, self.right_gpio_pin)


@dataclass
class SensorRig:
    lidar_port: str
    usb_camera_id: str
    dsi_camera_id: str

    def capture_frame(self) -> dict:
        # Point d'intégration matériel: TF-Luna + Logitech USB + Pi Cam V3 DSI.
        return {
            "lidar_distance_mm": None,
            "usb_camera_frame": None,
            "dsi_camera_frame": None,
        }
