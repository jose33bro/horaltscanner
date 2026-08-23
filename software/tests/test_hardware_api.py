import unittest

from flask import Flask

from software.api import laser_control, led_control, motor_control


class FakeMotorDriver:
    def __init__(self, connected=True):
        self.connected = connected

    def ensure_connected(self):
        if not self.connected:
            raise ConnectionError("STM32 unavailable")

    def motor_move(self, axis, distance, velocity=None):
        return {"axis": axis, "distance_mm": distance, "position_mm": distance, "steps": 10, "speed_steps_s": 100}

    def motor_home(self, axis):
        return {"axis": axis, "position_mm": 0.0, "homed": True}

    def motor_home_all(self):
        return {axis: {"axis": axis, "position_mm": 0.0, "homed": True} for axis in ("X", "Y", "Z")}

    def motor_stop(self):
        return {"stopped": True, "endstop_mask": 0}

    def motor_status(self):
        return {"connected": self.connected, "protocol": "binary_usb", "last_error": None, "axes": {}}


class FakeGPIODriver:
    def __init__(self):
        self.mode = "off"

    def laser_left_on(self):
        pass

    def laser_left_off(self):
        pass

    def laser_right_on(self):
        pass

    def laser_right_off(self):
        pass

    def laser_status(self):
        return {"left": False, "right": False, "simulation": True, "hardware_available": False}

    def led_set_rgb(self, r, g, b):
        self.mode = "rgb"

    def led_set_mode(self, mode):
        if mode == "invalid":
            raise ValueError("unknown LED mode: invalid")
        self.mode = mode

    def led_status(self):
        return {"r": 0, "g": 0, "b": 0, "simulation": True, "hardware_available": False}


class HardwareApiTests(unittest.TestCase):
    def _make_client(self, motor_driver, gpio_driver):
        app = Flask(__name__)
        motor_control.init_driver(motor_driver)
        laser_control.init_driver(gpio_driver)
        led_control.init_driver(gpio_driver)
        app.register_blueprint(motor_control.motor_bp)
        app.register_blueprint(laser_control.laser_bp)
        app.register_blueprint(led_control.led_bp)
        return app.test_client()

    def test_motor_endpoint_returns_503_when_driver_is_disconnected(self):
        client = self._make_client(FakeMotorDriver(connected=False), FakeGPIODriver())

        response = client.post("/api/motor/x/move", json={"distance": 1})

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.get_json()["ok"])

    def test_motor_endpoint_rejects_invalid_velocity_payload(self):
        client = self._make_client(FakeMotorDriver(), FakeGPIODriver())

        response = client.post("/api/motor/x/move", json={"distance": 1, "velocity": "fast"})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_led_mode_endpoint_rejects_unknown_mode(self):
        client = self._make_client(FakeMotorDriver(), FakeGPIODriver())

        response = client.post("/api/led/mode", json={"mode": "invalid"})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_legacy_laser_endpoint_contract_is_available(self):
        client = self._make_client(FakeMotorDriver(), FakeGPIODriver())

        response = client.post("/api/laser/left/on")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
