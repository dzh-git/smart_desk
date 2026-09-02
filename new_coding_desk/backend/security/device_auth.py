"""Fail-closed authentication for direct ESP32 seat controllers."""
from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path


ESP32_DEVICE_TOKENS_ENV = "SMARTDESK_ESP32_DEVICE_TOKENS_JSON"
ESP32_DEVICE_TOKENS_FILE_ENV = "SMARTDESK_ESP32_DEVICE_TOKENS_FILE"
MIN_DEVICE_TOKEN_LENGTH = 24


class DeviceAuthenticationError(ValueError):
    """Raised when a controller credential or binding is not valid."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Esp32Credential:
    device_id: str
    seat_id: int
    token: str


def parse_bearer_token(authorization: str | None) -> str | None:
    """Extract a strict Bearer token without logging or normalising it."""
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not token
        or token != token.strip()
        or " " in token
    ):
        return None
    return token


def load_esp32_credentials(
    raw: str | None = None,
) -> dict[str, Esp32Credential]:
    """Load explicit device-to-seat credentials from JSON or a protected file.

    Expected form:
      {"esp32-seat-01": {"seatId": 1, "token": "<24+ chars>"}}

    Invalid input produces an empty registry so production authentication
    fails closed instead of silently disabling itself.
    """
    if raw is None:
        source = os.environ.get(ESP32_DEVICE_TOKENS_ENV, "")
        if not source:
            configured_file = os.environ.get(
                ESP32_DEVICE_TOKENS_FILE_ENV,
                "",
            ).strip()
            if configured_file:
                try:
                    source = Path(configured_file).read_text(
                        encoding="utf-8",
                    )
                except OSError:
                    return {}
    else:
        source = raw
    try:
        payload = json.loads(source)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    credentials: dict[str, Esp32Credential] = {}
    for device_id, value in payload.items():
        if (
            not isinstance(device_id, str)
            or not device_id
            or not isinstance(value, dict)
        ):
            return {}
        seat_id = value.get("seatId")
        token = value.get("token")
        if (
            not isinstance(seat_id, int)
            or isinstance(seat_id, bool)
            or not 1 <= seat_id <= 9
            or not isinstance(token, str)
            or len(token) < MIN_DEVICE_TOKEN_LENGTH
        ):
            return {}
        credentials[device_id] = Esp32Credential(
            device_id=device_id,
            seat_id=seat_id,
            token=token,
        )
    return credentials


def authenticate_esp32_device(
    *,
    device_id: str,
    seat_id: int,
    authorization: str | None,
    credentials: dict[str, Esp32Credential] | None = None,
) -> None:
    """Authenticate one ESP32 and enforce its configured seat binding."""
    registry = (
        load_esp32_credentials()
        if credentials is None
        else credentials
    )
    credential = registry.get(device_id)
    if credential is None:
        raise DeviceAuthenticationError("DEVICE_AUTH_FAILED")
    if credential.seat_id != seat_id:
        raise DeviceAuthenticationError("DEVICE_SEAT_MISMATCH")
    supplied = parse_bearer_token(authorization)
    if supplied is None or not hmac.compare_digest(
        supplied,
        credential.token,
    ):
        raise DeviceAuthenticationError("DEVICE_AUTH_FAILED")


__all__ = [
    "ESP32_DEVICE_TOKENS_FILE_ENV",
    "ESP32_DEVICE_TOKENS_ENV",
    "DeviceAuthenticationError",
    "Esp32Credential",
    "authenticate_esp32_device",
    "load_esp32_credentials",
    "parse_bearer_token",
]
