"""Versioned JSON protocol shared by the ESP32 WebSocket endpoint.

This module validates transport evidence only. It deliberately contains no
meeting or seat business logic; accepted occupancy messages are delegated to
``SeatService`` by ``api/seat_ws.py``.
"""
from __future__ import annotations

import json
import re
from typing import Any

from backend.hardware.lighting_modes import LightingMode

SCHEMA_VERSION = 1
MAX_MESSAGE_BYTES = 4096
HEARTBEAT_INTERVAL_SECONDS = 5.0
HEARTBEAT_TIMEOUT_SECONDS = 18.0
COMMAND_ACK_TIMEOUT_SECONDS = 2.0
COMMAND_MAX_ATTEMPTS = 3
EVENT_CACHE_SIZE = 256

_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{3,96}$")
_UPLINK_TYPES = {
    "hello",
    "heartbeat",
    "occupancy",
    "command_ack",
    "sensor_error",
    "sync",
}


class ProtocolViolation(ValueError):
    """Stable protocol error that can be returned without exposing internals."""

    def __init__(self, code: str, message: str, *, fatal: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fatal = fatal


def _integer(
    payload: dict[str, Any],
    name: str,
    *,
    minimum: int = 0,
    maximum: int = 2_147_483_647,
) -> int:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolViolation(
            "FIELD_INVALID",
            f"{name} must be an integer",
        )
    if not minimum <= value <= maximum:
        raise ProtocolViolation(
            "FIELD_INVALID",
            f"{name} must be between {minimum} and {maximum}",
        )
    return value


def _identifier(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ProtocolViolation(
            "FIELD_INVALID",
            f"{name} has an invalid format",
        )
    return value


def _boolean(payload: dict[str, Any], name: str) -> bool:
    value = payload.get(name)
    if not isinstance(value, bool):
        raise ProtocolViolation(
            "FIELD_INVALID",
            f"{name} must be a boolean",
        )
    return value


def decode_uplink(raw: str | bytes, expected_seat_id: int) -> dict[str, Any]:
    """Decode and validate one ESP32-to-server protocol message."""
    encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ProtocolViolation(
            "MESSAGE_TOO_LARGE",
            f"message exceeds {MAX_MESSAGE_BYTES} bytes",
            fatal=True,
        )
    try:
        value = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolViolation("INVALID_JSON", "message must be UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ProtocolViolation("INVALID_MESSAGE", "message must be a JSON object")

    version = value.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ProtocolViolation(
            "UNSUPPORTED_SCHEMA_VERSION",
            f"schema_version must be {SCHEMA_VERSION}",
            fatal=True,
        )
    seat_id = _integer(value, "seat_id", minimum=1, maximum=9)
    if seat_id != expected_seat_id:
        raise ProtocolViolation(
            "SEAT_ID_MISMATCH",
            "message seat_id does not match WebSocket path",
            fatal=True,
        )
    message_type = value.get("type")
    if message_type not in _UPLINK_TYPES:
        raise ProtocolViolation(
            "TYPE_UNSUPPORTED",
            "message type is not supported",
        )

    if message_type == "hello":
        _identifier(value, "device_id")
        _identifier(value, "firmware_version")
        _identifier(value, "boot_id")
        capabilities = value.get("capabilities", [])
        if (
            not isinstance(capabilities, list)
            or len(capabilities) > 16
            or any(
                not isinstance(item, str) or len(item) > 48
                for item in capabilities
            )
        ):
            raise ProtocolViolation(
                "FIELD_INVALID",
                "capabilities must be a short string list",
            )
        return value

    _integer(value, "sequence")
    if message_type == "heartbeat":
        _integer(value, "uptime_ms", maximum=9_223_372_036_854_775_807)
        mode = value.get("current_mode")
        if not isinstance(mode, str) or not LightingMode.is_valid(mode):
            raise ProtocolViolation(
                "MODE_INVALID",
                "current_mode is not supported",
            )
        if "wifi_rssi" in value:
            _integer(value, "wifi_rssi", minimum=-150, maximum=0)
    elif message_type == "occupancy":
        _identifier(value, "event_id")
        _boolean(value, "occupied")
        _boolean(value, "pir")
        if value.get("distance_mm") is not None:
            _integer(value, "distance_mm", maximum=8190)
        if "sensor_ok" in value:
            _boolean(value, "sensor_ok")
    elif message_type == "command_ack":
        _identifier(value, "command_id")
        _boolean(value, "success")
        mode = value.get("current_mode")
        if not isinstance(mode, str) or not LightingMode.is_valid(mode):
            raise ProtocolViolation(
                "MODE_INVALID",
                "current_mode is not supported",
            )
        if value.get("error_code") is not None:
            _identifier(value, "error_code")
    elif message_type == "sensor_error":
        _identifier(value, "event_id")
        _identifier(value, "component")
        _identifier(value, "error_code")

    return value


def hello_ack_message(session_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "hello_ack",
        "session_id": session_id,
        "heartbeat_interval_ms": int(HEARTBEAT_INTERVAL_SECONDS * 1000),
        "heartbeat_timeout_ms": int(HEARTBEAT_TIMEOUT_SECONDS * 1000),
    }


def lighting_message(
    *,
    command_id: str,
    sequence: int,
    mode: str,
    brightness: int = 80,
) -> dict[str, Any]:
    if not LightingMode.is_valid(mode):
        raise ProtocolViolation("MODE_INVALID", "lighting mode is not supported")
    if not 0 <= brightness <= 255:
        raise ProtocolViolation(
            "BRIGHTNESS_INVALID",
            "brightness must be between 0 and 255",
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "lighting",
        "command_id": command_id,
        "sequence": sequence,
        "mode": mode,
        "brightness": brightness,
    }


def event_ack_message(
    event_id: str,
    *,
    accepted: bool,
    duplicate: bool = False,
    error_code: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": "event_ack",
        "event_id": event_id,
        "accepted": accepted,
        "duplicate": duplicate,
    }
    if error_code:
        message["error_code"] = error_code
    return message


def protocol_error_message(error: ProtocolViolation) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "protocol_error",
        "error_code": error.code,
        "message": error.message,
    }


__all__ = [
    "COMMAND_ACK_TIMEOUT_SECONDS",
    "COMMAND_MAX_ATTEMPTS",
    "EVENT_CACHE_SIZE",
    "HEARTBEAT_INTERVAL_SECONDS",
    "HEARTBEAT_TIMEOUT_SECONDS",
    "MAX_MESSAGE_BYTES",
    "ProtocolViolation",
    "SCHEMA_VERSION",
    "decode_uplink",
    "event_ack_message",
    "hello_ack_message",
    "lighting_message",
    "protocol_error_message",
]
