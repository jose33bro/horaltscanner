"""API package for HoralScanner."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

try:
    from flask import Flask as _Flask
except ModuleNotFoundError as exc:  # pragma: no cover - exercised when Flask is absent
    _FLASK_IMPORT_ERROR = exc
    _Flask = None
else:
    _FLASK_IMPORT_ERROR = None


def create_app() -> Flask:
    """Application factory.

    Creates and configures the Flask app, registers blueprints, and
    attaches centralized error handlers.
    """
    if _Flask is None:
        raise ModuleNotFoundError(
            "Flask is required to create the HoralScanner API app. "
            "Install the project dependencies with `pip install -r requirements.txt`."
        ) from _FLASK_IMPORT_ERROR

    app = _Flask(__name__)

    # Error handlers
    from api.middleware.errors import register_error_handlers
    register_error_handlers(app)

    # Blueprints
    from api.horalscanner_api import api_bp, scan_session
    from api.blueprints.scan import scan_bp
    from api.services import scan_service
    scan_service.configure(scan_session)
    app.register_blueprint(api_bp)
    app.register_blueprint(scan_bp)

    return app
