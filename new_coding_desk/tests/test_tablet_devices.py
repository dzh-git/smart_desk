"""Tablet provisioning and credential hashing tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
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
