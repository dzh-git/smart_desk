"""Tablet provisioning and credential hashing tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from backend.main import app
from backend.migrations import ensure_tablet_device_status_columns
from backend.models.tablet_device import TabletDevice
from backend.services.tablet_device_service import (
    TabletDeviceService,
    hash_device_token,
    verify_device_token,
)
from tests.conftest import TestSessionLocal

client = TestClient(app)

ADMIN_TOKEN = "test-provisioning-token-000001"
DEVICE_TOKEN = "test-device-secret-token-000001"


def _provision_direct() -> None:
    db = TestSessionLocal()
    try:
        TabletDeviceService(db).provision(
            device_id="tablet-seat-01",
            seat_id=1,
            token=DEVICE_TOKEN,
        )
    finally:
        db.close()


def _heartbeat_payload() -> dict:
    return {
        "seatId": 1,
        "appVersion": "0.8.0",
        "cameraStatus": "READY",
        "faceModelStatus": "READY",
        "registeredTemplatesCount": 3,
        "microphoneStatus": "READY",
        "meetingWebsocketStatus": "CONNECTED",
        "diagnosticStatus": "READY",
        "lastError": None,
    }


def test_token_hash_is_salted_and_verifiable():
    first = hash_device_token(DEVICE_TOKEN)
    second = hash_device_token(DEVICE_TOKEN)

    assert first != second
    assert DEVICE_TOKEN not in first
    assert verify_device_token(DEVICE_TOKEN, first)
    assert not verify_device_token("wrong-device-token-000000", first)


def test_provisioning_endpoint_is_disabled_without_admin_secret(monkeypatch):
    monkeypatch.delenv("SMARTDESK_DEVICE_PROVISIONING_TOKEN", raising=False)

    response = client.post(
        "/api/tablet-devices/provision",
        json={
            "deviceId": "tablet-seat-01",
            "seatId": 1,
            "deviceToken": DEVICE_TOKEN,
        },
    )

    assert response.status_code == 403
    assert (
        response.json()["error_code"]
        == "DEVICE_PROVISIONING_UNAUTHORIZED"
    )


def test_authorized_provisioning_stores_only_token_hash(monkeypatch):
    monkeypatch.setenv("SMARTDESK_DEVICE_PROVISIONING_TOKEN", ADMIN_TOKEN)

    response = client.post(
        "/api/tablet-devices/provision",
        headers={"X-SmartDesk-Provisioning-Token": ADMIN_TOKEN},
        json={
            "deviceId": "tablet-seat-01",
            "seatId": 1,
            "deviceToken": DEVICE_TOKEN,
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["deviceId"] == "tablet-seat-01"
    db = TestSessionLocal()
    try:
        stored = db.get(TabletDevice, "tablet-seat-01")
        assert stored is not None
        assert stored.token_hash != DEVICE_TOKEN
        assert verify_device_token(DEVICE_TOKEN, stored.token_hash)
    finally:
        db.close()


def test_one_tablet_per_seat():
    db = TestSessionLocal()
    try:
        service = TabletDeviceService(db)
        service.provision(
            device_id="tablet-seat-01",
            seat_id=1,
            token=DEVICE_TOKEN,
        )

        try:
            service.provision(
                device_id="tablet-seat-01-backup",
                seat_id=1,
                token="test-device-secret-token-000002",
            )
        except Exception as error:
            assert getattr(error, "error_code", None) == (
                "DEVICE_SEAT_ALREADY_BOUND"
            )
        else:
            raise AssertionError("Duplicate seat binding was accepted")
    finally:
        db.close()


def test_authenticated_heartbeat_persists_operational_status():
    _provision_direct()

    response = client.post(
        "/api/tablet-devices/tablet-seat-01/heartbeat",
        headers={"X-SmartDesk-Device-Token": DEVICE_TOKEN},
        json=_heartbeat_payload(),
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "deviceId": "tablet-seat-01",
        "seatId": 1,
        "enabled": True,
        "appVersion": "0.8.0",
        "lastSeenAt": response.json()["data"]["lastSeenAt"],
        "cameraStatus": "READY",
        "faceModelStatus": "READY",
        "registeredTemplatesCount": 3,
        "microphoneStatus": "READY",
        "meetingWebsocketStatus": "CONNECTED",
        "diagnosticStatus": "READY",
        "lastError": None,
    }
    db = TestSessionLocal()
    try:
        stored = db.get(TabletDevice, "tablet-seat-01")
        assert stored is not None
        assert stored.last_seen_at is not None
        assert stored.registered_templates_count == 3
        assert stored.meeting_websocket_status == "CONNECTED"
    finally:
        db.close()


def test_heartbeat_rate_limit_is_bounded_and_retryable(monkeypatch):
    from backend.api import tablet_devices as tablet_api

    _provision_direct()
    tablet_api.heartbeat_rate_limiter.clear()
    monkeypatch.setenv(
        "SMARTDESK_TABLET_HEARTBEAT_RATE_LIMIT_PER_MINUTE",
        "1",
    )
    first = client.post(
        "/api/tablet-devices/tablet-seat-01/heartbeat",
        headers={"X-SmartDesk-Device-Token": DEVICE_TOKEN},
        json=_heartbeat_payload(),
    )
    limited = client.post(
        "/api/tablet-devices/tablet-seat-01/heartbeat",
        headers={"X-SmartDesk-Device-Token": DEVICE_TOKEN},
        json=_heartbeat_payload(),
    )

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error_code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1
    tablet_api.heartbeat_rate_limiter.clear()


def test_heartbeat_rejects_wrong_token_and_seat():
    _provision_direct()
    wrong_token = client.post(
        "/api/tablet-devices/tablet-seat-01/heartbeat",
        headers={
            "X-SmartDesk-Device-Token":
                "wrong-device-secret-token-000001"
        },
        json=_heartbeat_payload(),
    )
    wrong_seat_payload = _heartbeat_payload()
    wrong_seat_payload["seatId"] = 2
    wrong_seat = client.post(
        "/api/tablet-devices/tablet-seat-01/heartbeat",
        headers={"X-SmartDesk-Device-Token": DEVICE_TOKEN},
        json=wrong_seat_payload,
    )

    assert wrong_token.status_code == 400
    assert wrong_token.json()["error_code"] == "DEVICE_AUTH_FAILED"
    assert wrong_seat.status_code == 400
    assert wrong_seat.json()["error_code"] == "DEVICE_SEAT_MISMATCH"


def test_heartbeat_rejects_invalid_or_unsupported_app_version(
    monkeypatch,
):
    from backend.api import tablet_devices as tablet_api

    _provision_direct()
    tablet_api.heartbeat_rate_limiter.clear()
    monkeypatch.setenv("SMARTDESK_TABLET_MIN_APP_VERSION", "0.8.0")
    invalid_payload = _heartbeat_payload()
    invalid_payload["appVersion"] = "unknown"
    invalid = client.post(
        "/api/tablet-devices/tablet-seat-01/heartbeat",
        headers={"X-SmartDesk-Device-Token": DEVICE_TOKEN},
        json=invalid_payload,
    )
    old_payload = _heartbeat_payload()
    old_payload["appVersion"] = "0.7.9"
    unsupported = client.post(
        "/api/tablet-devices/tablet-seat-01/heartbeat",
        headers={"X-SmartDesk-Device-Token": DEVICE_TOKEN},
        json=old_payload,
    )

    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "DEVICE_APP_VERSION_INVALID"
    assert unsupported.status_code == 400
    assert (
        unsupported.json()["error_code"]
        == "DEVICE_APP_VERSION_UNSUPPORTED"
    )


def test_hardware_status_separates_tablet_and_esp32_state(monkeypatch):
    _provision_direct()
    heartbeat = client.post(
        "/api/tablet-devices/tablet-seat-01/heartbeat",
        headers={"X-SmartDesk-Device-Token": DEVICE_TOKEN},
        json=_heartbeat_payload(),
    )
    assert heartbeat.status_code == 200

    response = client.get("/api/hardware/status")
    assert response.status_code == 200
    data = response.json()["data"]
    tablet = next(
        item for item in data["tablets"] if item["seat_id"] == 1
    )
    assert tablet["online"] is True
    assert tablet["camera_status"] == "READY"
    assert tablet["registered_templates_count"] == 3
    assert "seats" in data

    db = TestSessionLocal()
    try:
        stored = db.get(TabletDevice, "tablet-seat-01")
        assert stored is not None
        stored.last_seen_at = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        )
        db.commit()
    finally:
        db.close()
    monkeypatch.setenv(
        "SMARTDESK_TABLET_OFFLINE_TIMEOUT_SECONDS",
        "45",
    )

    stale = client.get("/api/hardware/status").json()["data"]
    stale_tablet = next(
        item for item in stale["tablets"] if item["seat_id"] == 1
    )
    assert stale_tablet["online"] is False
    assert stale_tablet["heartbeat_age_seconds"] >= 600


def test_tablet_status_migration_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE tablet_devices (
                    id VARCHAR(64) PRIMARY KEY,
                    seat_id INTEGER NOT NULL,
                    token_hash VARCHAR(256) NOT NULL,
                    enabled BOOLEAN NOT NULL,
                    app_version VARCHAR(64),
                    last_seen_at DATETIME,
                    last_error VARCHAR(300)
                )
                """
            )
        )
        connection.commit()

    ensure_tablet_device_status_columns(engine)
    ensure_tablet_device_status_columns(engine)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("tablet_devices")
    }
    assert {
        "camera_status",
        "face_model_status",
        "registered_templates_count",
        "microphone_status",
        "meeting_websocket_status",
        "diagnostic_status",
    }.issubset(columns)
