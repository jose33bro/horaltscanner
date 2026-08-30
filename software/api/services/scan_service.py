"""Scan service — compatibility layer around :class:`~api.scanner_engine.ScanSession`.

This module provides a thin, defensive wrapper so that blueprint code
does not directly import ``ScanSession``.  It also keeps the singleton
session instance isolated here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from api.scanner_engine import ScanSession
    _session: ScanSession = ScanSession(simulation=True)
except Exception as exc:  # pragma: no cover
    logger.warning("ScanSession unavailable: %s", exc)
    _session = None  # type: ignore[assignment]


def _get_state() -> dict:
    """Return current scan state, supporting both ``status`` and ``get_state`` methods."""
    if _session is None:
        return {"error": "scanner engine not available"}
    if callable(getattr(_session, "get_state", None)):
        return _session.get_state()  # type: ignore[return-value]
    if callable(getattr(_session, "status", None)):
        return _session.status()
    return {"error": "no state method found on scanner engine"}


def get_status() -> dict:
    """Return the current scan status."""
    return _get_state()


def start_scan() -> dict:
    """Start a new scan session."""
    if _session is None:
        return {"error": "scanner engine not available"}
    try:
        _session.start()
        return {"started": True, "status": _get_state()}
    except Exception as exc:  # noqa: BLE001
        return {"started": False, "error": str(exc)}


def stop_scan() -> dict:
    """Stop the current scan session."""
    if _session is None:
        return {"error": "scanner engine not available"}
    try:
        _session.stop()
        return {"stopped": True, "status": _get_state()}
    except Exception as exc:  # pragma: no cover
        return {"stopped": False, "error": str(exc)}
