"""API package for HoralScanner."""

from flask import Flask


def create_app() -> Flask:
    """Application factory.

    Creates and configures the Flask app, registers blueprints, and
    attaches centralized error handlers.
    """
    app = Flask(__name__)

    # Error handlers
    from api.middleware.errors import register_error_handlers
    register_error_handlers(app)

    # Blueprints
    from api.horalscanner_api import api_bp
    from api.blueprints.scan import scan_bp
    app.register_blueprint(api_bp)
    app.register_blueprint(scan_bp)

    return app
