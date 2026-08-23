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
                self.fan_status = {"speed": 0.0}

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

            def set_fan_speed(self, speed):
                self.calls.append(("set_fan_speed", speed))
                self.fan_status = {"speed": speed}
                return True

            def get_fan_status(self):
                return dict(self.fan_status)

        class FakeSTM32:
            def __init__(self):
                self.calls = []
                self.status = {
                    "positions": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "moving": {"x": False, "y": False, "z": False},
                    "temperature_c": 0.0,
                }
                self.fan_status = {"creality": 0.0, "temperature": 0.0}
                self.temperature = 32.5

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

            def set_fan_speed(self, fan, speed):
                self.calls.append(("set_fan_speed", fan, speed))
                self.fan_status[fan] = speed
                return True

            def get_fan_status(self):
                return dict(self.fan_status)

            def read_board_temperature(self):
                self.calls.append(("read_board_temperature",))
                return self.temperature

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

    def test_fan_routes_set_pwm_speeds(self):
        pi_response = self.client.post("/api/fan/pi", json={"speed": 0.5})
        creality_response = self.client.post("/api/fan/creality", json={"speed": 0.25})
        temperature_response = self.client.post("/api/fan/temperature", json={"percent": 75})

        self.assertEqual(pi_response.status_code, 200)
        self.assertEqual(creality_response.status_code, 200)
        self.assertEqual(temperature_response.status_code, 200)
        self.assertIn(("set_fan_speed", 0.5), self.fake_gpio.calls)
        self.assertIn(("set_fan_speed", "creality", 0.25), self.fake_stm32.calls)
        self.assertIn(("set_fan_speed", "temperature", 0.75), self.fake_stm32.calls)

    def test_fan_status_route_returns_all_fans(self):
        self.fake_gpio.fan_status = {"speed": 0.4}
        self.fake_stm32.fan_status = {"creality": 0.6, "temperature": 0.8}

        response = self.client.get("/api/fan/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["status"],
            {"pi": {"speed": 0.4}, "creality": 0.6, "temperature": 0.8},
        )

    def test_temperature_routes_read_board_sensor(self):
        board_response = self.client.get("/api/temperature/board")
        all_response = self.client.get("/api/temperature/all")

        self.assertEqual(board_response.status_code, 200)
        self.assertEqual(all_response.status_code, 200)
        self.assertEqual(board_response.get_json()["status"]["board_c"], 32.5)
        self.assertEqual(all_response.get_json()["status"]["sensor_pin"], "PC5")
        self.assertIn(("read_board_temperature",), self.fake_stm32.calls)

    def test_invalid_fan_speed_returns_400(self):
        response = self.client.post("/api/fan/pi", json={"speed": "fast"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
