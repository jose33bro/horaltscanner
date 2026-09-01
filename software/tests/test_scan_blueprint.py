"""Smoke tests for the scan blueprint and app factory."""

import sys
import os
import importlib
import unittest

# Ensure 'software/' is on the path (same as how -m api.app resolves imports)
_SOFTWARE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
if _SOFTWARE_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_SOFTWARE_DIR))

try:
    from flask import Flask  # noqa: F401
except ImportError:
    Flask = None


@unittest.skipIf(Flask is None, "Flask is required")
class TestCreateApp(unittest.TestCase):
    def test_create_app_returns_flask_app(self):
        from api import create_app
        app = create_app()
        self.assertIsInstance(app, Flask)

    def test_scan_blueprint_registered(self):
        from api import create_app
        app = create_app()
        rules = [r.rule for r in app.url_map.iter_rules()]
        self.assertIn("/scan/status", rules)
        self.assertIn("/scan/start", rules)
        self.assertIn("/scan/stop", rules)

    def test_runtime_api_routes_registered(self):
        from api import create_app
        app = create_app()
        rules = [r.rule for r in app.url_map.iter_rules()]
        self.assertIn("/api/status", rules)
        self.assertIn("/health", rules)
        self.assertIn("/api/health", rules)

    def test_api_app_import_path_initializes_app(self):
        for module_name in (
            "api.app",
            "api.horalscanner_api",
            "api",
            "software.api.horalscanner_api",
        ):
            sys.modules.pop(module_name, None)

        module = importlib.import_module("api.app")

        self.assertIsInstance(module.app, Flask)
        rules = [r.rule for r in module.app.url_map.iter_rules()]
        self.assertIn("/api/status", rules)
        self.assertIn("/health", rules)


@unittest.skipIf(Flask is None, "Flask is required")
class TestScanRoutes(unittest.TestCase):
    def setUp(self):
        from api import create_app
        self.app = create_app()
        self.client = self.app.test_client()

    def test_status_returns_200(self):
        resp = self.client.get("/scan/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, dict)
        # Either a real status or a degraded-mode error message is acceptable
        self.assertTrue("scanning" in data or "error" in data)

    def test_start_returns_json(self):
        resp = self.client.post("/scan/start")
        self.assertIn(resp.status_code, (200, 503))
        data = resp.get_json()
        self.assertIsInstance(data, dict)

    def test_stop_returns_json(self):
        resp = self.client.post("/scan/stop")
        self.assertIn(resp.status_code, (200, 503))
        data = resp.get_json()
        self.assertIsInstance(data, dict)

    def test_404_returns_json(self):
        resp = self.client.get("/nonexistent")
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
