"""
WebSocket integration tests — verifies that HTTP-synchronous routes trigger
real WebSocket events that are received by connected clients.

These tests use TestClient in context-manager mode so that the FastAPI
lifespan runs (capturing the main event loop and registering the
EventBus→WebSocket handler). Dev API is enabled so we can trigger
seat events without simulating hardware.

See:
    docs/WEBSOCKET_PROTOCOL.md §4 (connection lifecycle)
    docs/WEBSOCKET_PROTOCOL.md §8-9 (broadcast rules, event definitions)
    backend/websocket/event_handler.py (capture_loop + thread-safe broadcast)
"""
from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Base
from tests.conftest import TEST_ENGINE, TestSessionLocal


# ── Helpers ──────────────────────────────────────────────────────────────────


def _clean_tables() -> None:
    """Drop and recreate all tables, init seat states."""
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    db = TestSessionLocal()
    try:
        from backend.repositories.seat_repository import SeatRepository
        SeatRepository.init_seats(db)
    finally:
        db.close()


def _create_meeting(client: TestClient) -> int:
    """Create and start a meeting, return meeting_id."""
    resp = client.post(
        "/api/meetings",
        json={"title": "WS Integration Test", "description": ""},
    )
    assert resp.status_code == 201, f"Create meeting failed: {resp.json()}"
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")
    return mid


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_db():
    """Clean DB before each test."""
    _clean_tables()
    yield
    _clean_tables()


@pytest.fixture(scope="module")
def dev_enabled():
    """Enable ENABLE_DEMO_SEAT_API for the entire module.

    Uses module scope to minimise importlib.reload calls.
    """
    old = os.environ.get("ENABLE_DEMO_SEAT_API", "")
    os.environ["ENABLE_DEMO_SEAT_API"] = "true"
    from backend.api import dev
    importlib.reload(dev)
    yield
    if old:
        os.environ["ENABLE_DEMO_SEAT_API"] = old
    else:
        os.environ.pop("ENABLE_DEMO_SEAT_API", None)
    importlib.reload(dev)


# ── Tests ────────────────────────────────────────────────────────────────────


class TestWebSocketEvents:
    """Real WebSocket event delivery tests.

    Each test uses ``with TestClient(app) as client:`` to ensure the
    lifespan runs and the WS event handler is registered.
    """

    def test_connected_event_on_connect(self, dev_enabled):
        """Client receives 'connected' event immediately after connecting."""
        with TestClient(app) as client:
            mid = _create_meeting(client)

            with client.websocket_connect(f"/ws/{mid}?seat=0") as ws:
                data = ws.receive_json()

        assert data["event"] == "connected"
        assert data["meeting_id"] == mid
        assert isinstance(data["timestamp"], int)

    def test_seat_occupied_event_via_dev_api(self, dev_enabled):
        """POST /api/dev/seats/10/occupy → seat_occupied WebSocket event."""
        with TestClient(app) as client:
            mid = _create_meeting(client)

            with client.websocket_connect(f"/ws/{mid}?seat=0") as ws:
                # Consume connected event
                ws.receive_json()

                # Trigger seat_occupied via synchronous dev route
                resp = client.post("/api/dev/seats/10/occupy")
                assert resp.status_code == 200

                # Receive seat_occupied event
                data = ws.receive_json()

        assert data["event"] == "seat_occupied"
        assert data["meeting_id"] == mid
        assert data["payload"]["seat_id"] == 10

    def test_seat_vacant_event_via_dev_api(self, dev_enabled):
        """Occupy then vacate → seat_vacant WebSocket event."""
        with TestClient(app) as client:
            mid = _create_meeting(client)

            with client.websocket_connect(f"/ws/{mid}?seat=0") as ws:
                # Consume connected
                ws.receive_json()

                # Occupy first (triggers seat_occupied + checkin_prompt)
                client.post("/api/dev/seats/5/occupy")
                ws.receive_json()  # seat_occupied
                ws.receive_json()  # checkin_prompt

                # Now vacate
                resp = client.post("/api/dev/seats/5/vacate")
                assert resp.status_code == 200

                # Receive seat_vacant
                data = ws.receive_json()

        assert data["event"] == "seat_vacant"
        assert data["payload"]["seat_id"] == 5

    def test_service_call_created_event(self, dev_enabled):
        """POST /api/service-calls → service_call_created WebSocket event."""
        with TestClient(app) as client:
            mid = _create_meeting(client)

            with client.websocket_connect(f"/ws/{mid}?seat=0") as ws:
                # Consume connected
                ws.receive_json()

                # Create a service call via HTTP
                resp = client.post(
                    f"/api/service-calls?meeting_id={mid}",
                    json={"seat_id": 3, "service_type": "coffee"},
                )
                assert resp.status_code == 201

                # Receive service_call_created event
                data = ws.receive_json()

        assert data["event"] == "service_call_created"
        assert data["meeting_id"] == mid
        assert data["payload"]["seat_id"] == 3
        assert data["payload"]["service_type"] == "coffee"

    def test_multiple_clients_receive_broadcast(self, dev_enabled):
        """Two admin WS connections both receive the same seat_occupied."""
        with TestClient(app) as client:
            mid = _create_meeting(client)

            with (
                client.websocket_connect(f"/ws/{mid}?seat=0") as ws1,
                client.websocket_connect(f"/ws/{mid}?seat=0") as ws2,
            ):
                # Consume connected events
                ws1.receive_json()
                ws2.receive_json()

                # Trigger event
                client.post("/api/dev/seats/7/occupy")

                # Both clients should receive the event
                d1 = ws1.receive_json()
                d2 = ws2.receive_json()

        assert d1["event"] == "seat_occupied"
        assert d2["event"] == "seat_occupied"
        assert d1["payload"]["seat_id"] == 7
        assert d2["payload"]["seat_id"] == 7
