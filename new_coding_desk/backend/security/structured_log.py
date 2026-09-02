"""Structured security logging with recursive sensitive-field redaction."""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any


REDACTED = "[REDACTED]"
_SENSITIVE_FRAGMENTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
)


def redact_sensitive(value: Any, *, key: str = "") -> Any:
    """Return a JSON-safe copy with credential-like fields removed."""
    lowered = key.lower().replace("-", "").replace("_", "")
    if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(child_key): redact_sensitive(
                child_value,
                key=str(child_key),
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def log_security_event(
    logger: logging.Logger,
    *,
    event: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit one single-line JSON security event with stable base fields."""
    payload = redact_sensitive(
        {
            "log_type": "security_event",
            "event": event,
            **fields,
        }
    )
    logger.log(
        level,
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


__all__ = ["REDACTED", "log_security_event", "redact_sensitive"]
