"""Behavior tests for the WebSocket EventBridge.

Verifies that EventBus events are correctly routed to WebSocket rooms:
- events with meeting_id reach the correct room
- events without meeting_id broadcast to all rooms
- checkin_prompt targets only the specified seat
- get_or_create is called for new meeting_ids
- non-dict payloads are safely ignored
- _run_async thread-safety fallback
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from backend.services.event_bus import event_bus, BaseEvent
from backend.services.ws_service import WSService, MeetingRoom
from backend.services.ws_event_bridge import (
    EVENT_TO_WS_TYPE,
    _run_async,
    _make_ws_handler,
    register_ws_bridge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_event_bus():
    """Remove all handlers from the event_bus singleton between tests.

    EventBus.subscribe is not idempotent — registering the same handler
    twice causes duplicate calls. Tests that re-register handlers must
    start from a clean slate.
    """
    event_bus._handlers.clear()


# ---------------------------------------------------------------------------
# Structural tests (from original spec)
# ---------------------------------------------------------------------------

def test_all_events_mapped():
    """Verify all 15 spec events are mapped."""
    assert len(EVENT_TO_WS_TYPE) == 15
    expected = {
        "seat_occupied", "seat_vacant", "checkin_prompt", "check_in",
        "speaker_seat_set", "speaker_seat_clear",
        "meeting_started", "meeting_ended",
        "vote_started", "vote_updated", "vote_closed",
        "service_call_created", "service_call_resolved", "service_call_cancelled",
        "translation_final",
    }
    assert set(EVENT_TO_WS_TYPE.keys()) == expected


def test_register_bridge_does_not_raise():
    """Verify bridge registration succeeds (even without a running event loop)."""
    register_ws_bridge()


# ---------------------------------------------------------------------------
# Behavior tests: routing logic
# ---------------------------------------------------------------------------

class TestWSBridgeRouting:
    """Verify that EventBus events are routed to the correct WebSocket targets."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """Common setup: clear handlers, patch _run_async to capture coroutines."""
        _clear_event_bus()
        self.run_async_calls: list = []

        def _capture_run_async(coro):
            self.run_async_calls.append(coro)

        monkeypatch.setattr(
            "backend.services.ws_event_bridge._run_async",
            _capture_run_async,
        )

        # Re-register bridge so handlers capture the patched _run_async
        import backend.services.ws_event_bridge as bridge_mod
        for event_name in EVENT_TO_WS_TYPE:
            handler = bridge_mod._make_ws_handler(event_name)
            event_bus.subscribe(event_name, handler)

    def _run_captured_coros(self):
        """Execute all captured coroutines synchronously via asyncio.run()."""
        results = []
        for coro in self.run_async_calls:
            try:
                results.append(asyncio.run(coro))
            except Exception as exc:
                results.append(exc)
        self.run_async_calls.clear()
        return results

    # -- meeting_id routing -------------------------------------------------

    def test_event_with_meeting_id_broadcasts_to_room(self):
        """Event with meeting_id routes broadcast to that specific room."""
        import backend.services.ws_event_bridge as bridge_mod

        mock_room = MeetingRoom(meeting_id=42)
        broadcast_calls = []
        original_broadcast = mock_room.broadcast

        async def tracking_broadcast(msg, exclude_seat=None):
            broadcast_calls.append((msg, exclude_seat))
            await original_broadcast(msg, exclude_seat=exclude_seat)
        mock_room.broadcast = tracking_broadcast

        # Directly replace get_or_create on the singleton
        bridge_mod.ws_svc.get_or_create = lambda mid: mock_room

        try:
            event = BaseEvent(name="seat_occupied", payload={"meeting_id": 42, "seat_id": 1})
            event_bus.publish(event)
            self._run_captured_coros()

            assert len(broadcast_calls) == 1
            msg, exclude = broadcast_calls[0]
            assert msg["type"] == "seat_occupied"
            assert msg["payload"]["meeting_id"] == 42
        finally:
            # Restore original method
            del bridge_mod.ws_svc.get_or_create

    def test_event_without_meeting_id_broadcasts_all_rooms(self):
        """Event without meeting_id broadcasts to every existing room."""
        import backend.services.ws_event_bridge as bridge_mod

        room1 = MeetingRoom(meeting_id=1)
        room2 = MeetingRoom(meeting_id=2)
        broadcast_1 = []
        broadcast_2 = []

        async def track1(msg, **kw):
            broadcast_1.append(msg)
        async def track2(msg, **kw):
            broadcast_2.append(msg)
        room1.broadcast = track1
        room2.broadcast = track2

        original_rooms = bridge_mod.ws_svc.rooms
        bridge_mod.ws_svc.rooms = {1: room1, 2: room2}

        try:
            event = BaseEvent(name="translation_final", payload={"text": "hello"})
            event_bus.publish(event)
            self._run_captured_coros()

            assert len(broadcast_1) == 1
            assert len(broadcast_2) == 1
            assert broadcast_1[0]["type"] == "translation_result"
            assert broadcast_2[0]["type"] == "translation_result"
        finally:
            bridge_mod.ws_svc.rooms = original_rooms

    # -- checkin_prompt routing ---------------------------------------------

    def test_checkin_prompt_with_seat_id_sends_to_target_seat(self):
        """checkin_prompt with seat_id sends to target seat only, not broadcast."""
        import backend.services.ws_event_bridge as bridge_mod

        mock_room = MeetingRoom(meeting_id=42)
        send_calls = []
        broadcast_calls = []

        async def track_send(seat_id, msg):
            send_calls.append((seat_id, msg))
        async def track_broadcast(msg, exclude_seat=None):
            broadcast_calls.append((msg, exclude_seat))

        mock_room.send_to_seat = track_send
        mock_room.broadcast = track_broadcast

        bridge_mod.ws_svc.get_or_create = lambda mid: mock_room

        try:
            event = BaseEvent(
                name="checkin_prompt",
                payload={"meeting_id": 42, "seat_id": 5, "attendee_name": "Alice"},
            )
            event_bus.publish(event)
            self._run_captured_coros()

            assert len(send_calls) == 1
            assert send_calls[0][0] == 5
            assert send_calls[0][1]["type"] == "checkin_prompt"
            assert send_calls[0][1]["payload"]["seat_id"] == 5
            assert len(broadcast_calls) == 0
        finally:
            del bridge_mod.ws_svc.get_or_create

    def test_checkin_prompt_without_seat_id_falls_back_to_broadcast(self):
        """checkin_prompt without seat_id falls back to room broadcast."""
        import backend.services.ws_event_bridge as bridge_mod

        mock_room = MeetingRoom(meeting_id=42)
        broadcast_calls = []

        async def track_broadcast(msg, exclude_seat=None):
            broadcast_calls.append((msg, exclude_seat))

        mock_room.broadcast = track_broadcast

        bridge_mod.ws_svc.get_or_create = lambda mid: mock_room

        try:
            event = BaseEvent(
                name="checkin_prompt",
                payload={"meeting_id": 42, "attendee_name": "Bob"},
            )
            event_bus.publish(event)
            self._run_captured_coros()

            assert len(broadcast_calls) == 1
            assert broadcast_calls[0][0]["type"] == "checkin_prompt"
        finally:
            del bridge_mod.ws_svc.get_or_create

    # -- get_or_create -----------------------------------------------------

    def test_event_with_unknown_meeting_id_creates_room(self):
        """Event with meeting_id not in rooms triggers get_or_create."""
        import backend.services.ws_event_bridge as bridge_mod

        fresh_svc = WSService()
        assert 99 not in fresh_svc.rooms

        bridge_mod.ws_svc.get_or_create = fresh_svc.get_or_create
        original_rooms = bridge_mod.ws_svc.rooms
        bridge_mod.ws_svc.rooms = fresh_svc.rooms

        try:
            event = BaseEvent(name="meeting_started", payload={"meeting_id": 99})
            event_bus.publish(event)
            self._run_captured_coros()

            assert 99 in fresh_svc.rooms
        finally:
            del bridge_mod.ws_svc.get_or_create
            bridge_mod.ws_svc.rooms = original_rooms

    # -- payload guard ------------------------------------------------------

    def test_non_dict_payload_is_safely_ignored(self):
        """Handler does not crash when payload is not a dict."""
        event = BaseEvent(name="seat_occupied", payload=None)

        # Should not raise
        event_bus.publish(event)

        # No coroutines should have been scheduled (payload guard returned early)
        assert len(self.run_async_calls) == 0

    # -- WS type mapping ----------------------------------------------------

    def test_event_name_maps_to_correct_ws_type(self):
        """Each event type produces the correct WS message type."""
        import backend.services.ws_event_bridge as bridge_mod

        mock_room = MeetingRoom(meeting_id=1)
        captured_msg = {}

        async def capture(msg, **kw):
            captured_msg["type"] = msg["type"]

        mock_room.broadcast = capture

        bridge_mod.ws_svc.get_or_create = lambda mid: mock_room

        try:
            event = BaseEvent(name="speaker_seat_set", payload={"meeting_id": 1})
            event_bus.publish(event)
            self._run_captured_coros()
            assert captured_msg["type"] == "speaker_seat_set"
        finally:
            del bridge_mod.ws_svc.get_or_create


# ---------------------------------------------------------------------------
# Thread-safety tests for _run_async
# ---------------------------------------------------------------------------

class TestRunAsyncThreadSafety:
    """Verify _run_async correctly handles cross-thread scenarios."""

    def test_ensure_future_on_main_loop(self):
        """When called from asyncio thread, uses ensure_future."""
        called = False

        async def dummy():
            nonlocal called
            called = True

        async def _test():
            _run_async(dummy())
            await asyncio.sleep(0.01)

        asyncio.run(_test())
        assert called

    def test_run_coroutine_threadsafe_from_other_thread(self):
        """When called from a non-asyncio thread, uses run_coroutine_threadsafe."""
        import backend.services.ws_event_bridge as bridge_mod

        done = threading.Event()

        async def set_done():
            done.set()

        async def main():
            bridge_mod._loop = asyncio.get_running_loop()

            done_in_thread = threading.Event()

            def thread_target():
                bridge_mod._run_async(set_done())
                done_in_thread.set()

            t = threading.Thread(target=thread_target)
            t.start()
            t.join(timeout=5)

            await asyncio.sleep(0.2)
            return done.is_set() and done_in_thread.is_set()

        result = asyncio.run(main())
        assert result, "_run_async from non-asyncio thread did not schedule on main loop"


# ---------------------------------------------------------------------------
# Integration: full pipeline from publish to WS call
# ---------------------------------------------------------------------------

def test_full_pipeline_publish_to_broadcast():
    """End-to-end: publish event -> handler runs -> ws_svc methods called."""
    _clear_event_bus()
    import backend.services.ws_event_bridge as bridge_mod

    mock_room = MeetingRoom(meeting_id=1)
    broadcast_msgs = []

    async def capture(msg, **kw):
        broadcast_msgs.append(msg)

    mock_room.broadcast = capture

    bridge_mod.ws_svc.get_or_create = lambda mid: mock_room

    # Patch _run_async to run synchronously
    def sync_run(coro):
        asyncio.run(coro)

    original_run_async = bridge_mod._run_async
    bridge_mod._run_async = sync_run

    try:
        # Re-register so handlers capture the patched _run_async
        for event_name in EVENT_TO_WS_TYPE:
            handler = bridge_mod._make_ws_handler(event_name)
            event_bus.subscribe(event_name, handler)

        event = BaseEvent(
            name="service_call_created",
            payload={"meeting_id": 1, "service_type": "coffee", "seat_id": 3},
        )
        event_bus.publish(event)

        assert len(broadcast_msgs) == 1
        assert broadcast_msgs[0]["type"] == "service_update"
        assert broadcast_msgs[0]["payload"]["service_type"] == "coffee"
        assert broadcast_msgs[0]["payload"]["seat_id"] == 3
    finally:
        bridge_mod._run_async = original_run_async
        del bridge_mod.ws_svc.get_or_create
