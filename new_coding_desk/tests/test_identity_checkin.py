"""Android identity integration: stable Person and guarded seat check-in."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from backend.main import app
from backend.migrations import ensure_attendee_identity_columns
from backend.models.seat_state import SeatState
from tests.conftest import TestSessionLocal

client = TestClient(app)


def _prepare_active_attendee(
    *,
    person_id: str = "person_001",
    seat_id: int = 1,
) -> tuple[int, dict]:
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
    assert attendee_response.json()["data"]["person_id"] == person_id

    start_response = client.post(f"/api/meetings/{meeting_id}/start")
    assert start_response.status_code == 200

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
        "personId": person_id,
        "deviceId": f"tablet-seat-{seat_id:02d}",
        "deviceSeatId": seat_id,
        "status": "VERIFIED",
        "similarity": 0.82,
        "thresholdStatus": "VALIDATED",
        "verificationLevel": "VALIDATED",
        "modelVersion": "future-validated-model",
    }
    return meeting_id, payload


def test_people_endpoint_rejects_duplicate_stable_id():
    payload = {"id": "person_001", "name": "Alice"}
    assert client.post("/api/people", json=payload).status_code == 201

    duplicate = client.post("/api/people", json=payload)

    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "PERSON_ALREADY_EXISTS"


def test_validated_identity_delegates_to_existing_checkin_state_machine():
    _, payload = _prepare_active_attendee()

    response = client.post("/api/seats/1/identity-checkin", json=payload)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "checked_in"
    assert response.json()["data"]["attendee_id"] is not None


def test_device_bound_seat_must_match_url_seat():
    _, payload = _prepare_active_attendee()
    payload["deviceSeatId"] = 2

    response = client.post("/api/seats/1/identity-checkin", json=payload)

    assert response.status_code == 400
    assert response.json()["error_code"] == "DEVICE_SEAT_MISMATCH"


def test_calibration_pending_identity_cannot_check_in():
    _, payload = _prepare_active_attendee()
    payload.update(
        {
            "thresholdStatus": "CALIBRATION_PENDING",
            "verificationLevel": "PROTOTYPE",
        }
    )

    response = client.post("/api/seats/1/identity-checkin", json=payload)

    assert response.status_code == 400
    assert response.json()["error_code"] == "FACE_CALIBRATION_PENDING"


def test_prototype_identity_is_blocked_by_default():
    _, payload = _prepare_active_attendee()
    payload.update(
        {
            "thresholdStatus": "PROVISIONAL",
            "verificationLevel": "PROTOTYPE",
        }
    )

    response = client.post("/api/seats/1/identity-checkin", json=payload)

    assert response.status_code == 400
    assert (
        response.json()["error_code"]
        == "PROTOTYPE_IDENTITY_CHECKIN_DISABLED"
    )


def test_prototype_identity_can_be_enabled_for_explicit_development(
    monkeypatch,
):
    _, payload = _prepare_active_attendee()
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

    response = client.post("/api/seats/1/identity-checkin", json=payload)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "checked_in"


def test_identity_person_must_belong_to_active_meeting():
    _, payload = _prepare_active_attendee()
    other_person = client.post(
        "/api/people",
        json={"id": "person_002", "name": "Bob"},
    )
    assert other_person.status_code == 201
    payload["personId"] = "person_002"

    response = client.post("/api/seats/1/identity-checkin", json=payload)

    assert response.status_code == 400
    assert response.json()["error_code"] == "PERSON_NOT_IN_ACTIVE_MEETING"


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
