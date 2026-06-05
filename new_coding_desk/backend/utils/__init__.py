"""Shared API-layer helpers — unified response envelope."""
from __future__ import annotations


def _ok(data=None, message: str = "OK") -> dict:
    """Build unified success response dict.

    Per API_SPEC §1:
        {"success": true, "message": "OK", "data": {...}}
    """
    return {"success": True, "message": message, "data": data}
