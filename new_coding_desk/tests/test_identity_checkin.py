"""Trusted Android identity check-in, idempotency, and legacy migration."""
from __future__ import annotations

from uuid import uuid4
import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from backend.events import event_bus
from backend.main import app
from backend.migrations import ensure_attendee_identity_columns
from backend.models.attendee import Attendee
from backend.models.identity_checkin_event import IdentityCheckInEvent
from backend.models.seat_state import SeatState
from backend.services.seat_service import SeatService
from backend.services.tablet_device_service import TabletDeviceService
from tests.conftest import TestSessionLocal

client = TestClient(app)

DEVICE_TOKEN = "test-tablet-device-token-000001"


def _provision_device(
    *,
    device_id: str = "tablet-seat-01",
    seat_id: int = 1,
    token: str = DEVICE_TOKEN,
) -> None:
    db = TestSessionLocal()
    try:
        TabletDeviceService(db).provision(
            device_id=device_id,
            seat_id=seat_id,
            token=token,
        )
    finally:
        db.close()


def _prepare_active_attendee(
    *,
    person_id: str = "person_001",
    seat_id: int = 1,
    start_meeting: bool = True,
    occupy_seat: bool = True,
    provision_device: bool = True,
) -> tuple[int, int, dict, dict]:
    if provision_device:
        _provision_device(seat_id=seat_id)

    person_response = client.post(
        "/api/people",
        json={"id": person_id, "name": "Alice"},
    )
    assert person_response.status_code == 201

    meeting_response = client.post(
        "/api/meetings",
        json={"title": "Identity Test"},
    )
    assert meeting_response.status_code == 201
    meeting_id = meeting_response.json()["data"]["id"]

    attendee_response = client.post(
        f"/api/meetings/{meeting_id}/attendees",
        json={
            "name": "Alice",
            "title": "Engineer",
            "personId": person_id,
        },
    )
    assert attendee_response.status_code == 200
    attendee_id = attendee_response.json()["data"]["id"]
    assert attendee_response.json()["data"]["person_id"] == person_id

    if start_meeting:
        start_response = client.post(f"/api/meetings/{meeting_id}/start")
        assert start_response.status_code == 200

    if occupy_seat:
        db = TestSessionLocal()
        try:
            seat = db.get(SeatState, seat_id)
            assert seat is not None
            seat.status = "occupied_unchecked"
            seat.attendee_id = None
            db.commit()
        finally:
            db.close()

    payload = {
        "eventId": f"identity-{uuid4().hex}",
        "personCode": person_id,
        "deviceId": f"tablet-seat-{seat_id:02d}",
        "deviceSeatId": seat_id,
        "status": "VERIFIED",
        "similarity": 0.82,
        "thresholdStatus": "VALIDATED",
        "verificationLevel": "VALIDATED",
        "modelVersion": "future-validated-model",
        "eventTimestamp": int(time.time() * 1000),
    }
    headers = {"X-SmartDesk-Device-Token": DEVICE_TOKEN}
    return meeting_id, attendee_id, payload, headers


def _identity_post(
    seat_id: int,
    payload: dict,
    headers: dict | None,
):
    return client.post(
        f"/api/seats/{seat_id}/identity-checkin",
        json=payload,
        headers=headers or {},
    )


def test_people_endpoint_rejects_duplicate_stable_id():
    payload = {"id": "person_001", "name": "Alice"}
    assert client.post("/api/people", json=payload).status_code == 201

    duplicate = client.post("/api/people", json=payload)

    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "PERSON_ALREADY_EXISTS"


def test_validated_identity_delegates_to_existing_checkin_state_machine():
    _, _, payload, headers = _prepare_active_attendee()

    response = _identity_post(1, payload, headers)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "checked_in"
    assert response.json()["data"]["attendee_id"] is not None


def test_stale_and_future_identity_events_are_rejected(monkeypatch):
    _, _, payload, headers = _prepare_active_attendee()
    now_ms = int(time.time() * 1000)
    payload["eventTimestamp"] = now_ms - 121_000

    stale = _identity_post(1, payload, headers)

    assert stale.status_code == 400
    assert stale.json()["error_code"] == "IDENTITY_EVENT_STALE"

    payload["eventId"] = f"identity-{uuid4().hex}"
    payload["eventTimestamp"] = now_ms + 31_000
    future = _identity_post(1, payload, headers)

    assert future.status_code == 400
    assert future.json()["error_code"] == "IDENTITY_EVENT_FUTURE"


def test_identity_rate_limit_has_stable_error_and_retry_header(
    monkeypatch,
):
    from backend.api import seats as seats_api

    _, _, payload, headers = _prepare_active_attendee()
    seats_api.identity_rate_limiter.clear()
    monkeypatch.setenv(
        "SMARTDESK_IDENTITY_RATE_LIMIT_PER_MINUTE",
        "1",
    )
    first = _identity_post(1, payload, headers)
    payload["eventId"] = f"identity-{uuid4().hex}"
    payload["eventTimestamp"] = int(time.time() * 1000)

    limited = _identity_post(1, payload, headers)

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error_code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1
    seats_api.identity_rate_limiter.clear()


def test_identity_checkin_rolls_back_all_state_when_event_write_fails(
    monkeypatch,
):
    _, attendee_id, payload, _ = _prepare_active_attendee()
    db = TestSessionLocal()
    try:
        service = SeatService(db, event_bus)

        def fail_event_write(*_args, **_kwargs):
            raise RuntimeError("simulated identity event write failure")

        monkeypatch.setattr(
            service.identity_event_repo,
            "save",
            fail_event_write,
        )
        try:
            service.identity_check_in(
                seat_id=1,
                device_seat_id=payload["deviceSeatId"],
                device_id=payload["deviceId"],
                device_token=DEVICE_TOKEN,
                event_id=payload["eventId"],
                event_timestamp=payload["eventTimestamp"],
                person_id=payload["personCode"],
                identity_status=payload["status"],
                threshold_status=payload["thresholdStatus"],
                verification_level=payload["verificationLevel"],
                similarity=payload["similarity"],
                model_version=payload["modelVersion"],
            )
        except RuntimeError as error:
            assert "simulated" in str(error)
        else:
            raise AssertionError("Injected event write failure did not raise")

        db.expire_all()
        seat = db.get(SeatState, 1)
        attendee = db.get(Attendee, attendee_id)
        event = db.get(IdentityCheckInEvent, payload["eventId"])
        assert seat is not None and seat.status == "occupied_unchecked"
        assert seat.attendee_id is None
        assert attendee is not None and attendee.checked_in is False
        assert attendee.seat_id is None
        assert event is None
    finally:
        db.close()


def test_device_token_is_required():
    _, _, payload, _ = _prepare_active_attendee()

    response = _identity_post(1, payload, None)

    assert response.status_code == 400
    assert response.json()["error_code"] == "DEVICE_AUTH_FAILED"


def test_unprovisioned_device_is_rejected():
    _, _, payload, headers = _prepare_active_attendee(
        provision_device=False,
    )

    response = _identity_post(1, payload, headers)

    assert response.status_code == 404
    assert response.json()["error_code"] == "DEVICE_NOT_PROVISIONED"


def test_device_bound_seat_must_match_url_seat():
    _, _, payload, headers = _prepare_active_attendee()
    payload["deviceSeatId"] = 2

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "DEVICE_SEAT_MISMATCH"


def test_registry_binding_must_match_url_seat():
    _, _, payload, headers = _prepare_active_attendee(
        provision_device=False,
    )
    _provision_device(device_id="tablet-seat-01", seat_id=2)

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "DEVICE_SEAT_MISMATCH"


def test_repeated_event_is_idempotent_and_broadcasts_checkin_once():
    _, _, payload, headers = _prepare_active_attendee()
    received = []

    def capture(event):
        received.append(event)

    event_bus.subscribe("check_in", capture)
    try:
        first = _identity_post(1, payload, headers)
        second = _identity_post(1, payload, headers)
    finally:
        event_bus.unsubscribe("check_in", capture)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]
    assert len(received) == 1


def test_event_id_cannot_be_reused_for_different_person():
    _, _, payload, headers = _prepare_active_attendee()
    assert _identity_post(1, payload, headers).status_code == 200
    payload["personCode"] = "person_002"

    response = _identity_post(1, payload, headers)

    assert response.status_code == 409
    assert response.json()["error_code"] == "IDENTITY_EVENT_CONFLICT"


def test_new_event_for_same_checked_in_person_is_safe():
    _, _, payload, headers = _prepare_active_attendee()
    assert _identity_post(1, payload, headers).status_code == 200
    payload["eventId"] = f"identity-{uuid4().hex}"

    response = _identity_post(1, payload, headers)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "checked_in"


def test_no_active_meeting_is_rejected():
    _, _, payload, headers = _prepare_active_attendee(start_meeting=False)

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "NO_ACTIVE_MEETING"


def test_unknown_person_is_rejected():
    _, _, payload, headers = _prepare_active_attendee()
    payload["personCode"] = "person_missing"

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "PERSON_NOT_FOUND"


def test_identity_person_must_belong_to_active_meeting():
    _, _, payload, headers = _prepare_active_attendee()
    other_person = client.post(
        "/api/people",
        json={"id": "person_002", "name": "Bob"},
    )
    assert other_person.status_code == 201
    payload["personCode"] = "person_002"

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "PERSON_NOT_IN_ACTIVE_MEETING"


def test_vacant_seat_does_not_allow_identity_checkin():
    _, _, payload, headers = _prepare_active_attendee(occupy_seat=False)

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "SEAT_NOT_OCCUPIED"


def test_person_already_checked_into_other_seat_is_rejected():
    _, attendee_id, payload, headers = _prepare_active_attendee()
    db = TestSessionLocal()
    try:
        attendee = db.get(Attendee, attendee_id)
        seat_two = db.get(SeatState, 2)
        assert attendee is not None and seat_two is not None
        attendee.checked_in = True
        attendee.seat_id = 2
        seat_two.status = "checked_in"
        seat_two.attendee_id = attendee_id
        db.commit()
    finally:
        db.close()

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "ATTENDEE_ALREADY_CHECKED_IN"


def test_seat_with_other_attendee_is_rejected():
    meeting_id, _, payload, headers = _prepare_active_attendee()
    person = client.post(
        "/api/people",
        json={"id": "person_002", "name": "Bob"},
    )
    assert person.status_code == 201
    other = client.post(
        f"/api/meetings/{meeting_id}/attendees",
        json={"name": "Bob", "personId": "person_002"},
    )
    assert other.status_code == 200
    other_id = other.json()["data"]["id"]

    db = TestSessionLocal()
    try:
        attendee = db.get(Attendee, other_id)
        seat = db.get(SeatState, 1)
        assert attendee is not None and seat is not None
        attendee.checked_in = True
        attendee.seat_id = 1
        seat.status = "checked_in"
        seat.attendee_id = other_id
        db.commit()
    finally:
        db.close()

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] in {
        "SEAT_NOT_OCCUPIED",
        "SEAT_ALREADY_CHECKED_IN",
    }


def test_unknown_identity_status_never_triggers_checkin():
    _, _, payload, headers = _prepare_active_attendee()
    payload["status"] = "UNKNOWN"

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "IDENTITY_NOT_VERIFIED"


def test_invalid_verification_level_is_rejected():
    _, _, payload, headers = _prepare_active_attendee()
    payload["verificationLevel"] = "UNTRUSTED"

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert (
        response.json()["error_code"]
        == "IDENTITY_VERIFICATION_LEVEL_INVALID"
    )


def test_calibration_pending_identity_cannot_check_in():
    _, _, payload, headers = _prepare_active_attendee()
    payload.update(
        {
            "thresholdStatus": "CALIBRATION_PENDING",
            "verificationLevel": "PROTOTYPE",
        }
    )

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert response.json()["error_code"] == "FACE_CALIBRATION_PENDING"


def test_prototype_identity_is_blocked_by_default():
    _, _, payload, headers = _prepare_active_attendee()
    payload.update(
        {
            "thresholdStatus": "PROVISIONAL",
            "verificationLevel": "PROTOTYPE",
        }
    )

    response = _identity_post(1, payload, headers)

    assert response.status_code == 400
    assert (
        response.json()["error_code"]
        == "PROTOTYPE_IDENTITY_CHECKIN_DISABLED"
    )


def test_prototype_identity_can_be_enabled_for_explicit_development(
    monkeypatch,
):
    _, _, payload, headers = _prepare_active_attendee()
    payload.update(
        {
            "thresholdStatus": "PROVISIONAL",
            "verificationLevel": "PROTOTYPE",
        }
    )
    monkeypatch.setenv(
        "SMARTDESK_ALLOW_PROTOTYPE_IDENTITY_CHECKIN",
        "true",
    )

    response = _identity_post(1, payload, headers)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "checked_in"


def test_existing_sqlite_attendees_table_receives_identity_column_and_index():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE attendees (
                    id INTEGER PRIMARY KEY,
                    meeting_id INTEGER NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    title VARCHAR(100),
                    seat_id INTEGER,
                    checked_in BOOLEAN
                )
                """
            )
        )

    ensure_attendee_identity_columns(engine)
    inspector = inspect(engine)

    assert "person_id" in {
        column["name"]
        for column in inspector.get_columns("attendees")
    }
    assert "ix_attendees_meeting_person_id" in {
        index["name"]
        for index in inspector.get_indexes("attendees")
    }
