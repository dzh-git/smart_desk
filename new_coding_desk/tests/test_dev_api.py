"""Tests for dev API endpoints and demo seed data (Phase 03)."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Base
from backend.repositories.seat_repository import SeatRepository
from tests.conftest import TEST_ENGINE, TestSessionLocal

client = TestClient(app)


def _create_meeting() -> int:
    """Create and start a meeting, return meeting_id."""
    resp = client.post("/api/meetings", json={"title": "Dev Test Meeting", "description": ""})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")
    return mid


# ── Dev API disabled by default ──────────────────────────────────────────────


class TestDevAPIDisabled:
    """When ENABLE_DEMO_SEAT_API is not set, endpoints return 404."""

    def test_occupy_returns_404_when_disabled(self):
        """POST /api/dev/seats/1/occupy returns 404 by default."""
        resp = client.post("/api/dev/seats/1/occupy")
        assert resp.status_code == 404

    def test_vacate_returns_404_when_disabled(self):
        """POST /api/dev/seats/1/vacate returns 404 by default."""
        resp = client.post("/api/dev/seats/1/vacate")
        assert resp.status_code == 404


# ── Dev API enabled ──────────────────────────────────────────────────────────


class TestDevAPIEnabled:
    """When ENABLE_DEMO_SEAT_API=true, dev seat endpoints work."""

    @pytest.fixture(autouse=True)
    def enable_dev_api(self):
        """Enable the dev API for this test class."""
        old = os.environ.get("ENABLE_DEMO_SEAT_API", "")
        os.environ["ENABLE_DEMO_SEAT_API"] = "true"
        # Re-import triggers re-evaluation of ENABLED
        import importlib
        from backend.api import dev
        importlib.reload(dev)
        yield
        if old:
            os.environ["ENABLE_DEMO_SEAT_API"] = old
        else:
            del os.environ["ENABLE_DEMO_SEAT_API"]
        importlib.reload(dev)

    def test_occupy_transitions_to_occupied_unchecked(self):
        """POST /api/dev/seats/1/occupy transitions seat to occupied_unchecked."""
        _create_meeting()
        resp = client.post("/api/dev/seats/1/occupy")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["seat_id"] == 1
        assert body["data"]["status"] == "occupied_unchecked"

    def test_occupy_fails_when_already_occupied(self):
        """POST /api/dev/seats/1/occupy fails if seat already occupied."""
        _create_meeting()
        client.post("/api/dev/seats/1/occupy")
        resp = client.post("/api/dev/seats/1/occupy")
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False

    def test_occupy_fails_nonexistent_seat(self):
        """POST /api/dev/seats/99/occupy returns 404."""
        _create_meeting()
        resp = client.post("/api/dev/seats/99/occupy")
        assert resp.status_code == 404

    def test_vacate_transitions_to_vacant(self):
        """POST /api/dev/seats/1/vacate transitions seat to vacant."""
        _create_meeting()
        client.post("/api/dev/seats/1/occupy")
        resp = client.post("/api/dev/seats/1/vacate")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "vacant"

    def test_occupy_then_list_seats(self):
        """After dev occupy, seat state visible via /api/seats."""
        _create_meeting()
        client.post("/api/dev/seats/2/occupy")
        resp = client.get("/api/seats")
        body = resp.json()
        seats = {s["seat_id"]: s for s in body["data"]}
        assert seats[2]["status"] == "occupied_unchecked"

    def test_vacate_clears_attendee_binding(self):
        """Dev vacate also clears attendee seat_id and checked_in."""
        mid = _create_meeting()
        # Create attendee
        resp = client.post(f"/api/meetings/{mid}/attendees", json={"name": "Test User", "title": "Tester"})
        attendee_id = resp.json()["data"]["id"]
        # Occupy + check-in
        client.post("/api/dev/seats/1/occupy")
        client.post(f"/api/seats/1/checkin", json={"attendee_id": attendee_id})
        # Verify attendee is checked in
        resp = client.get(f"/api/meetings/{mid}/attendees")
        attendees = {a["id"]: a for a in resp.json()["data"]}
        assert attendees[attendee_id]["checked_in"] is True
        assert attendees[attendee_id]["seat_id"] == 1
        # Vacate via dev API
        client.post("/api/dev/seats/1/vacate")
        # Verify attendee is unbound
        resp = client.get(f"/api/meetings/{mid}/attendees")
        attendees = {a["id"]: a for a in resp.json()["data"]}
        assert attendees[attendee_id]["checked_in"] is False
        assert attendees[attendee_id]["seat_id"] is None

    def test_vacate_allows_recheckin_via_dev(self):
        """After dev vacate, same attendee can check in again."""
        mid = _create_meeting()
        resp = client.post(f"/api/meetings/{mid}/attendees", json={"name": "Test User", "title": "Tester"})
        attendee_id = resp.json()["data"]["id"]
        # Cycle 1: occupy → check-in → vacate
        client.post("/api/dev/seats/2/occupy")
        client.post(f"/api/seats/2/checkin", json={"attendee_id": attendee_id})
        client.post("/api/dev/seats/2/vacate")
        # Cycle 2: re-occupy → re-check-in
        client.post("/api/dev/seats/2/occupy")
        resp = client.post(f"/api/seats/2/checkin", json={"attendee_id": attendee_id})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "checked_in"


# ── Demo seed disabled by default ────────────────────────────────────────────


class TestDemoSeedDisabled:
    """When ENABLE_DEMO_SEED is not set, no demo data is created."""

    def test_no_demo_meeting_on_fresh_db(self):
        """No demo meeting exists when seed is disabled."""
        resp = client.get("/api/meetings")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_no_demo_vote(self):
        """No open vote when seed is disabled."""
        resp = client.get("/api/votes/active")
        assert resp.status_code == 200
        assert resp.json()["data"] is None


# ── Demo seed enabled ────────────────────────────────────────────────────────


class TestDemoSeedEnabled:
    """When ENABLE_DEMO_SEED=true, demo data is created on fresh DB."""

    @pytest.fixture(autouse=True)
    def enable_demo_seed(self):
        """Enable demo seed for this test class."""
        old = os.environ.get("ENABLE_DEMO_SEED", "")
        os.environ["ENABLE_DEMO_SEED"] = "true"
        # Re-run seed by triggering startup actions
        yield
        if old:
            os.environ["ENABLE_DEMO_SEED"] = old
        else:
            del os.environ["ENABLE_DEMO_SEED"]

    def _run_seed(self):
        """Manually run seed_demo_data to simulate startup."""
        from backend.seed_demo import seed_demo_data
        db = TestSessionLocal()
        try:
            seed_demo_data(db)
        finally:
            db.close()

    def test_creates_active_meeting(self):
        """Demo seed creates an active meeting."""
        self._run_seed()
        resp = client.get("/api/meetings/active")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] is not None
        assert body["data"]["status"] == "active"

    def test_creates_agendas(self):
        """Demo seed creates agenda items."""
        self._run_seed()
        resp = client.get("/api/meetings/active")
        mid = resp.json()["data"]["id"]
        resp = client.get(f"/api/meetings/{mid}/agendas")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 5

    def test_creates_attendees(self):
        """Demo seed creates attendees."""
        self._run_seed()
        resp = client.get("/api/meetings/active")
        mid = resp.json()["data"]["id"]
        resp = client.get(f"/api/meetings/{mid}/attendees")
        assert resp.status_code == 200
        attendees = resp.json()["data"]
        assert len(attendees) == 8
        # Some checked in, some not
        checked_in = [a for a in attendees if a["checked_in"]]
        unbound = [a for a in attendees if a["seat_id"] is None]
        assert len(checked_in) == 4
        assert any(unbound)  # at least one unbound attendee

    def test_creates_mixed_seat_states(self):
        """Demo seed creates seats with mixed states."""
        self._run_seed()
        resp = client.get("/api/seats")
        assert resp.status_code == 200
        seats = resp.json()["data"]
        assert len(seats) == 10
        states = {s["seat_id"]: s["status"] for s in seats}
        # Seats 1-4: checked_in
        assert all(states[i] == "checked_in" for i in range(1, 5))
        # Seats 5-6: occupied_unchecked
        assert all(states[i] == "occupied_unchecked" for i in range(5, 7))
        # Seats 7-10: vacant
        assert all(states[i] == "vacant" for i in range(7, 11))

    def test_speaker_seat_set(self):
        """Demo seed sets speaker seat to seat 1."""
        self._run_seed()
        resp = client.get("/api/seats/speaker")
        assert resp.status_code == 200
        assert resp.json()["data"]["seat_id"] == 1

    def test_creates_open_vote(self):
        """Demo seed creates an open vote."""
        self._run_seed()
        resp = client.get("/api/votes/active")
        assert resp.status_code == 200
        vote = resp.json()["data"]
        assert vote is not None
        assert vote["status"] == "open"
        assert len(vote["options"]) == 3

    def test_creates_service_call(self):
        """Demo seed creates a pending service call."""
        self._run_seed()
        resp = client.get("/api/meetings/active")
        mid = resp.json()["data"]["id"]
        resp = client.get(f"/api/service-calls?meeting_id={mid}")
        assert resp.status_code == 200
        calls = resp.json()["data"]
        assert len(calls) >= 1
        assert any(c["status"] == "pending" for c in calls)

    def test_creates_translation_records(self):
        """Demo seed creates translation records."""
        self._run_seed()
        resp = client.get("/api/meetings/active")
        mid = resp.json()["data"]["id"]
        resp = client.get(f"/api/translations?meeting_id={mid}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["entries"]) >= 2

    def test_idempotent_on_repeated_call(self):
        """Running seed multiple times does not duplicate data."""
        self._run_seed()
        self._run_seed()  # second call
        resp = client.get("/api/meetings")
        assert len(resp.json()["data"]) == 1

    def test_does_not_modify_existing_meetings(self):
        """Seed skips when meetings already exist."""
        # Create a real meeting first
        client.post("/api/meetings", json={"title": "Real Meeting", "description": ""})
        self._run_seed()  # should not add demo data
        resp = client.get("/api/meetings")
        meetings = resp.json()["data"]
        assert len(meetings) == 1
        assert meetings[0]["title"] == "Real Meeting"
