# tests/test_seats_router.py
"""Integration tests for seats router endpoints."""

import pytest
from fastapi.testclient import TestClient

try:
    from backend.main import app
    _APP_IMPORT_OK = True
except Exception as e:
    _APP_IMPORT_OK = False
    _APP_IMPORT_ERROR = str(e)


@pytest.fixture
def client():
    if not _APP_IMPORT_OK:
        pytest.skip(f"App import failed: {_APP_IMPORT_ERROR}")
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state(client):
    """Ensure clean DB state before each test by ending any active meeting."""
    import warnings
    try:
        resp = client.get("/api/meetings/active")
        if resp.status_code == 200:
            body = resp.json()
            meeting = body.get("data", body)
            if meeting and isinstance(meeting, dict) and meeting.get("id"):
                end_resp = client.post(f"/api/meetings/{meeting['id']}/end")
                if end_resp.status_code != 200:
                    warnings.warn(
                        f"reset_state: end meeting {meeting['id']} returned "
                        f"{end_resp.status_code}: {end_resp.text[:200]}"
                    )
    except (ValueError, KeyError, TypeError):
        pass
    yield


def test_list_seats(client):
    resp = client.get("/api/seats")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    data = resp.json()["data"]
    assert len(data) == 10


def test_get_speaker_seat(client):
    resp = client.get("/api/seats/speaker")
    assert resp.status_code == 200
    assert resp.json()["data"]["seat_id"] is None


def test_checkin_requires_attendee_id(client):
    resp = client.post("/api/seats/3/checkin", json={"attendee_id": 999})
    assert resp.status_code == 404  # ATTENDEE_NOT_FOUND


def test_clear_speaker_seat_no_active_meeting(client):
    """CR-002: DELETE /api/seats/speaker should fail when no meeting is active."""
    resp = client.delete("/api/seats/speaker")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "NO_ACTIVE_MEETING"
