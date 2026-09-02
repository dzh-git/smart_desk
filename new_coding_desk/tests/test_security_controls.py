"""Deterministic tests for bounded anti-abuse and log redaction helpers."""
from __future__ import annotations

import json
import logging

from backend.security.device_auth import (
    DeviceAuthenticationError,
    authenticate_esp32_device,
    load_esp32_credentials,
    parse_bearer_token,
)
from backend.security.rate_limit import SlidingWindowRateLimiter
from backend.security.structured_log import (
    REDACTED,
    log_security_event,
    redact_sensitive,
)
from backend.security.version_compat import (
    meets_minimum_version,
    parse_semantic_version,
)


def test_esp32_credential_parser_and_seat_binding_fail_closed():
    token = "esp32-unit-test-token-000001"
    credentials = load_esp32_credentials(
        (
            '{"esp32-seat-01":'
            f'{{"seatId":1,"token":"{token}"}}'
            "}"
        )
    )
    authenticate_esp32_device(
        device_id="esp32-seat-01",
        seat_id=1,
        authorization=f"Bearer {token}",
        credentials=credentials,
    )

    try:
        authenticate_esp32_device(
            device_id="esp32-seat-01",
            seat_id=2,
            authorization=f"Bearer {token}",
            credentials=credentials,
        )
    except DeviceAuthenticationError as error:
        assert error.code == "DEVICE_SEAT_MISMATCH"
    else:
        raise AssertionError("Cross-seat ESP32 binding was accepted")

    assert load_esp32_credentials("{bad json") == {}
    assert parse_bearer_token(f"Basic {token}") is None


def test_sliding_window_limit_and_key_memory_bound():
    limiter = SlidingWindowRateLimiter(max_keys=2)
    assert limiter.check(
        "device-a",
        limit=2,
        window_seconds=10,
        now=0,
    ).allowed
    assert limiter.check(
        "device-a",
        limit=2,
        window_seconds=10,
        now=1,
    ).allowed
    denied = limiter.check(
        "device-a",
        limit=2,
        window_seconds=10,
        now=2,
    )
    assert denied.allowed is False
    assert denied.retry_after_seconds == 8
    assert limiter.check(
        "device-a",
        limit=2,
        window_seconds=10,
        now=11,
    ).allowed
    limiter.check("device-b", limit=1, window_seconds=10, now=11)
    limiter.check("device-c", limit=1, window_seconds=10, now=11)
    assert limiter.key_count == 2


def test_structured_security_log_redacts_nested_secrets(caplog):
    secret = "do-not-log-this-device-secret"
    payload = redact_sensitive(
        {
            "device_id": "tablet-seat-01",
            "Authorization": f"Bearer {secret}",
            "nested": {"device_token": secret},
        }
    )
    assert payload["Authorization"] == REDACTED
    assert payload["nested"]["device_token"] == REDACTED

    logger = logging.getLogger("tests.security")
    with caplog.at_level(logging.INFO, logger=logger.name):
        log_security_event(
            logger,
            event="test_event",
            device_id="tablet-seat-01",
            device_token=secret,
            result="accepted",
        )

    assert secret not in caplog.text
    record = json.loads(caplog.records[-1].message)
    assert record["log_type"] == "security_event"
    assert record["device_token"] == REDACTED


def test_semantic_version_compatibility_is_strict_and_ordered():
    assert parse_semantic_version("0.8.0") is not None
    assert parse_semantic_version("0.8") is None
    assert parse_semantic_version("unknown") is None
    assert meets_minimum_version("0.8.1", "0.8.0")
    assert meets_minimum_version("1.0.0", "0.8.0")
    assert not meets_minimum_version("0.7.9", "0.8.0")
    assert not meets_minimum_version("0.8.0-rc.1", "0.8.0")
    assert meets_minimum_version("0.8.0", "0.8.0-rc.1")
