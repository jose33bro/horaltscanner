import importlib
import unittest

try:
    from flask import Flask  # noqa: F401
except Exception:  # pragma: no cover
    Flask = None


@unittest.skipIf(Flask is None, "Flask is required for API tests")
class HoralScannerAPITests(unittest.TestCase):
    def setUp(self):
        self.api_module = importlib.import_module("software.api.horalscanner_api")

        class FakeGPIO:
            def __init__(self):
                self.calls = []
                self.laser_status = {"left": False, "right": False}
                self.led_status = {"r": 0, "g": 0, "b": 0}

            def laser_on(self, side):
                self.calls.append(("laser_on", side))
                self.laser_status[side] = True
                return True

            def laser_off(self, side):
                self.calls.append(("laser_off", side))
                self.laser_status[side] = False
                return True

            def led_set(self, r, g, b):
                self.calls.append(("led_set", r, g, b))
                self.led_status = {"r": r, "g": g, "b": b}
                return True

            def get_laser_status(self):
                return dict(self.laser_status)

            def get_led_status(self):
                return dict(self.led_status)

        class FakeSTM32:
            def __init__(self):
                self.calls = []
                self.status = {
                    "positions": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "moving": {"x": False, "y": False, "z": False},
                    "temperature_c": 0.0,
                }

            def move_motor(self, axis, distance):
                self.calls.append(("move_motor", axis, distance))
                return True

            def home_motor(self, axis):
                self.calls.append(("home_motor", axis))
                return True

            def stop_motor(self, axis="all"):
                self.calls.append(("stop_motor", axis))
                return True

            def get_motor_status(self):
                return dict(self.status)

        self.fake_gpio = FakeGPIO()
        self.fake_stm32 = FakeSTM32()

        self.api_module.gpio_driver = self.fake_gpio
        self.api_module.stm32_driver = self.fake_stm32

        self.client = self.api_module.app.test_client()

    def test_laser_route_uses_gpio_driver(self):
        response = self.client.post("/api/laser/left", json={"state": True})

        self.assertEqual(response.status_code, 200)
        self.assertIn(("laser_on", "left"), self.fake_gpio.calls)

    def test_led_route_uses_gpio_driver(self):
        response = self.client.post("/api/led/color", json={"r": 255, "g": 0, "b": 5})

        self.assertEqual(response.status_code, 200)
        self.assertIn(("led_set", 255, 0, 5), self.fake_gpio.calls)

    def test_move_and_home_routes_use_stm32_driver(self):
        move_response = self.client.post("/api/move/x", json={"mm": 10})
        home_response = self.client.post("/api/home/all", json={})

        self.assertEqual(move_response.status_code, 200)
        self.assertEqual(home_response.status_code, 200)
        self.assertIn(("move_motor", "x", 10.0), self.fake_stm32.calls)
        self.assertIn(("home_motor", "all"), self.fake_stm32.calls)

    def test_motor_status_and_stop_routes_use_stm32_driver(self):
        status_response = self.client.get("/api/motor/status")
        stop_response = self.client.post("/api/motor/stop", json={"axis": "z"})

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(stop_response.status_code, 200)
        self.assertEqual(status_response.get_json()["status"], self.fake_stm32.status)
        self.assertIn(("stop_motor", "z"), self.fake_stm32.calls)

    def test_invalid_numeric_payloads_return_400(self):
        led_response = self.client.post("/api/led/color", json={"r": "red", "g": 0, "b": 0})
        move_response = self.client.post("/api/move/x", json={"mm": "far"})

        self.assertEqual(led_response.status_code, 400)
        self.assertEqual(move_response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
