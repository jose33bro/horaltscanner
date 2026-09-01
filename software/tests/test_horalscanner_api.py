import importlib
import unittest

try:
    from flask import Flask  # noqa: F401
except Exception:  # pragma: no cover
    Flask = None


@unittest.skipIf(Flask is None, "Flask is required for API tests")
class HoralScannerAPITests(unittest.TestCase):
    def setUp(self):
        from api import create_app

        self.api_module = importlib.import_module("api.horalscanner_api")
        self.app = create_app()

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

            def read_cpu_temperature(self):
                return 47.25

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

            @property
            def connected(self):
                return True

        self.fake_gpio = FakeGPIO()
        self.fake_stm32 = FakeSTM32()

        self.api_module.gpio_driver = self.fake_gpio
        self.api_module.stm32_driver = self.fake_stm32

        self.client = self.app.test_client()

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
        self.assertEqual(all_response.get_json()["status"]["board_c"], 32.5)
        self.assertEqual(all_response.get_json()["status"]["pi_cpu_c"], 47.25)
        self.assertIn(("read_board_temperature",), self.fake_stm32.calls)

    def test_invalid_fan_speed_returns_400(self):
        response = self.client.post("/api/fan/pi", json={"speed": "fast"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/fan/pi", json={"speed": 50})
        self.assertEqual(response.status_code, 400)

    def test_fan_percent_value_is_scaled(self):
        response = self.client.post("/api/fan/pi", json={"percent": 1})
        self.assertEqual(response.status_code, 200)
        self.assertIn(("set_fan_speed", 0.01), self.fake_gpio.calls)

    def test_fan_route_returns_502_when_driver_fails(self):
        self.fake_gpio.set_fan_speed = lambda _: False
        response = self.client.post("/api/fan/pi", json={"speed": 0.5})
        self.assertEqual(response.status_code, 502)

    def test_temperature_all_reports_unavailable_board_sensor(self):
        self.fake_stm32.read_board_temperature = lambda: None
        response = self.client.get("/api/temperature/all")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["status"]["board_c"])

    def test_api_status_returns_health(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"]["api"], "ok")
        self.assertTrue(data["status"]["gpio_driver"])
        self.assertTrue(data["status"]["stm32_driver"])
        self.assertIn("version", data["status"])

    def test_status_includes_runtime_capabilities(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertIn("capabilities", data)
        self.assertIn("simulation_mode", data["status"])
        self.assertIn("acquisition_backend_ready", data["capabilities"])

    def test_scan_start_falls_back_to_simulation(self):
        self.api_module.scan_session = self.api_module.ScanSession(simulation=False)
        response = self.client.post("/api/scan/start")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["status"]["simulation"])
        self.assertEqual(data["mode"], "simulation")

    def test_reconstruct_without_points_returns_structured_error(self):
        response = self.client.post("/api/model/reconstruct")
        self.assertEqual(response.status_code, 409)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn("hint", data)

    def test_health_endpoints_return_ok(self):
        for route in ("/health", "/api/health"):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"status": "ok"})

    def test_laser_status_route(self):
        self.fake_gpio.laser_status = {"left": True, "right": False}
        response = self.client.get("/api/laser/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], {"left": True, "right": False})

    def test_led_status_route(self):
        self.fake_gpio.led_status = {"r": 10, "g": 20, "b": 30}
        response = self.client.get("/api/led/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], {"r": 10, "g": 20, "b": 30})

    def test_cors_headers_present(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")

    def test_dashboard_static_assets_are_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/app.js").status_code, 200)
        self.assertEqual(self.client.get("/style.css").status_code, 200)
        self.assertEqual(self.client.get("/viewer3d.js").status_code, 200)

    def test_lidar_read_route_returns_measurement(self):
        class FakeLidar:
            connected = True

            def read_distance_mm(self):
                return 432.1

            def get_offset(self):
                return -2.0

        original = self.api_module.lidar_driver
        self.addCleanup(setattr, self.api_module, "lidar_driver", original)
        self.api_module.lidar_driver = FakeLidar()

        response = self.client.post("/api/lidar/read")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["distance_mm"], 432.1)

    def test_camera_test_route_returns_quality_metrics(self):
        class FakeCamera:
            is_open = True

            def open(self):
                return True

            def capture_jpeg(self):
                return b"jpeg"

        original_camera = self.api_module.pi_camera
        original_analyzer = self.api_module.analyze_camera_frame
        self.addCleanup(setattr, self.api_module, "pi_camera", original_camera)
        self.addCleanup(setattr, self.api_module, "analyze_camera_frame", original_analyzer)
        self.api_module.pi_camera = FakeCamera()
        self.api_module.analyze_camera_frame = lambda _: {
            "analysis_available": True,
            "width": 1920,
            "height": 1080,
            "brightness": 120.0,
            "sharpness": 300.0,
            "checkerboard_found": True,
        }

        response = self.client.post("/api/camera/pi/test")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["result"]["checkerboard_found"])

    def test_camera_usb_status_reports_available_when_open_succeeds(self):
        class FakeUsbCamera:
            def __init__(self):
                self.is_open = False

            def open(self):
                self.is_open = True
                return True

        original_camera = self.api_module.usb_camera
        self.addCleanup(setattr, self.api_module, "usb_camera", original_camera)
        self.api_module.usb_camera = FakeUsbCamera()

        response = self.client.get("/api/camera/usb/status")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["success"])
        self.assertTrue(body["available"])

    def test_camera_usb_status_reports_unavailable_when_open_fails(self):
        class FakeUsbCamera:
            is_open = False

            def open(self):
                return False

        original_camera = self.api_module.usb_camera
        self.addCleanup(setattr, self.api_module, "usb_camera", original_camera)
        self.api_module.usb_camera = FakeUsbCamera()

        response = self.client.get("/api/camera/usb/status")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["available"])

    def test_camera_usb_frame_returns_200_when_fallback_opened_stream_works(self):
        class FakeUsbCamera:
            def __init__(self):
                self.is_open = False

            def open(self):
                self.is_open = True
                return True

            def capture_jpeg(self):
                return b"jpeg-bytes"

        original_camera = self.api_module.usb_camera
        self.addCleanup(setattr, self.api_module, "usb_camera", original_camera)
        self.api_module.usb_camera = FakeUsbCamera()

        response = self.client.get("/api/camera/usb/frame")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"jpeg-bytes")

    def test_camera_usb_frame_returns_503_when_camera_unavailable(self):
        class FakeUsbCamera:
            is_open = False

            def open(self):
                return False

        original_camera = self.api_module.usb_camera
        self.addCleanup(setattr, self.api_module, "usb_camera", original_camera)
        self.api_module.usb_camera = FakeUsbCamera()

        response = self.client.get("/api/camera/usb/frame")

        self.assertEqual(response.status_code, 503)

    def test_scan_control_routes_share_session_status(self):
        original = self.api_module.scan_session
        self.api_module.scan_session = self.api_module.ScanSession(simulation=True)
        self.addCleanup(setattr, self.api_module, "scan_session", original)
        self.addCleanup(self.api_module.scan_session.stop)

        start_response = self.client.post("/api/scan/start")
        status_response = self.client.get("/api/scan/status")
        stop_response = self.client.post("/api/scan/stop")

        self.assertEqual(start_response.status_code, 200)
        self.assertTrue(status_response.get_json()["status"]["scanning"])
        self.assertEqual(stop_response.status_code, 200)
        self.assertFalse(stop_response.get_json()["status"]["scanning"])

    def test_api_status_no_gpio_driver(self):
        self.api_module.gpio_driver = None
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["status"]["gpio_driver"])

    def test_api_status_no_stm32_driver(self):
        self.api_module.stm32_driver = None
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["status"]["stm32_driver"])

    def test_laser_align_turns_on_laser_and_returns_analysis(self):
        class FakeCamera:
            is_open = True

            def open(self):
                return True

            def capture_jpeg(self):
                return b"jpeg"

        original_camera = self.api_module.pi_camera
        original_analyzer = self.api_module.analyze_laser_line
        self.addCleanup(setattr, self.api_module, "pi_camera", original_camera)
        self.addCleanup(setattr, self.api_module, "analyze_laser_line", original_analyzer)
        self.api_module.pi_camera = FakeCamera()
        self.api_module.analyze_laser_line = lambda _: {
            "analysis_available": True,
            "line_detected": True,
            "angle_deg": 1.2,
            "correction_deg": -1.2,
            "instruction": "Tourner à gauche de -1.2°",
        }

        response = self.client.post("/api/laser/align/left")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["side"], "left")
        self.assertTrue(data["line_detected"])
        self.assertEqual(data["angle_deg"], 1.2)
        self.assertIn("gauche", data["side_label"])
        # Laser should have been turned on then off
        self.assertIn(("laser_on", "left"), self.fake_gpio.calls)
        self.assertIn(("laser_off", "left"), self.fake_gpio.calls)

    def test_laser_align_invalid_side_returns_400(self):
        response = self.client.post("/api/laser/align/invalid")
        self.assertEqual(response.status_code, 400)

    def test_laser_align_no_gpio_returns_503(self):
        original_gpio = self.api_module.gpio_driver
        self.api_module.gpio_driver = None
        self.addCleanup(setattr, self.api_module, "gpio_driver", original_gpio)
        response = self.client.post("/api/laser/align/left")
        self.assertEqual(response.status_code, 503)

if __name__ == "__main__":
    unittest.main()
