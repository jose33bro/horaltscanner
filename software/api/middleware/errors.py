"""Centralized JSON error handlers for HoralScanner API."""

from flask import jsonify


def register_error_handlers(app):
    """Register JSON error handlers on *app*."""

    @app.errorhandler(400)
    def bad_request(exc):
        return jsonify({"error": "Bad Request", "detail": str(exc)}), 400

    @app.errorhandler(404)
    def not_found(exc):
        return jsonify({"error": "Not Found", "detail": str(exc)}), 404

    @app.errorhandler(405)
    def method_not_allowed(exc):
        return jsonify({"error": "Method Not Allowed", "detail": str(exc)}), 405

    @app.errorhandler(500)
    def internal_error(exc):
        return jsonify({"error": "Internal Server Error", "detail": str(exc)}), 500

    @app.errorhandler(Exception)
    def unhandled_exception(exc):
        app.logger.exception("Unhandled exception: %s", exc)
        return jsonify({"error": "Internal Server Error"}), 500
