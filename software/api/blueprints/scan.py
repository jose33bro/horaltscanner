"""Scan blueprint — routes for controlling and querying the 3D scan process."""

from flask import Blueprint, jsonify, request

from api.services import scan_service

scan_bp = Blueprint("scan", __name__, url_prefix="/scan")


@scan_bp.route("/start", methods=["POST"])
def start():
    """Start a new scan session."""
    result = scan_service.start_scan()
    status_code = 200 if result.get("started") else 409
    return jsonify(result), status_code


@scan_bp.route("/status", methods=["GET"])
def status():
    """Return current scan status."""
    return jsonify(scan_service.get_status()), 200


@scan_bp.route("/preflight", methods=["GET", "POST"])
def preflight():
    """Return readiness blockers, probing hardware for POST requests."""
    return jsonify(scan_service.preflight(probe=request.method == "POST")), 200


@scan_bp.route("/stop", methods=["POST"])
def stop():
    """Stop the current scan session."""
    result = scan_service.stop_scan()
    status_code = 200 if result.get("stopped") else 503
    return jsonify(result), status_code
