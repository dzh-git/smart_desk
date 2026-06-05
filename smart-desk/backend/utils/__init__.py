"""Shared router helpers."""


def _ok(data):
    """Return unified success response envelope."""
    return {"success": True, "message": "OK", "data": data}
