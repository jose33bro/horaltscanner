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
    _session: ScanSession | None = None
except Exception as exc:  # pragma: no cover
    logger.warning("ScanSession unavailable: %s", exc)
    _session = None  # type: ignore[assignment]


def configure(session: ScanSession) -> None:
    """Attach the application-wide session used by both scan route prefixes."""
    global _session
    _session = session


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
        blockers = list(getattr(exc, "blockers", []))
        return {
            "started": False,
            "error": "Real scan preflight failed" if blockers else str(exc),
            "blockers": blockers,
            "status": _get_state(),
        }


def preflight(*, probe: bool = False) -> dict:
    """Return the active acquisition mode and actionable readiness blockers."""
    if _session is None:
        return {
            "ready": False,
            "mode": "unavailable",
            "blockers": ["scanner engine not available"],
        }
    return _session.readiness(probe=probe)


def stop_scan() -> dict:
    """Stop the current scan session."""
    if _session is None:
        return {"error": "scanner engine not available"}
    try:
        _session.stop()
        return {"stopped": True, "status": _get_state()}
    except Exception as exc:  # pragma: no cover
        return {"stopped": False, "error": str(exc)}
