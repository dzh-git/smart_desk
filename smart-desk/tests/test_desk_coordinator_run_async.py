"""Thread-safety tests for desk_coordinator._run_async (CR-004 fix)
and EventBus publishing integration (SR-002).

The original _run_async used asyncio.run() from non-asyncio threads,
which creates a new event loop. WebSocket transports are bound to
their accepting loop, so messages were silently lost.

The fix (mirrors ws_event_bridge._run_async):
- Capture main loop via set_main_loop() at startup
- Use asyncio.run_coroutine_threadsafe() for cross-thread scheduling
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from backend.services.event_bus import event_bus, BaseEvent


class TestDeskCoordinatorRunAsync:
    """Verify desk_coordinator._run_async is thread-safe (CR-004)."""

    def test_ensure_future_on_main_loop(self):
        """When called from asyncio thread, uses ensure_future."""
        import backend.services.desk_coordinator as dc

        called = False

        async def dummy():
            nonlocal called
            called = True

        async def _test():
            dc._run_async(dummy())
            await asyncio.sleep(0.01)

        asyncio.run(_test())
        assert called

    def test_run_coroutine_threadsafe_from_other_thread(self):
        """When called from non-asyncio thread, uses run_coroutine_threadsafe."""
        import backend.services.desk_coordinator as dc

        done = threading.Event()

        async def set_done():
            done.set()

        async def main():
            dc.set_main_loop()

            def thread_target():
                dc._run_async(set_done())

            t = threading.Thread(target=thread_target)
            t.start()
            t.join(timeout=5)

            await asyncio.sleep(0.2)
            return done.is_set()

        result = asyncio.run(main())
        assert result, "_run_async from non-asyncio thread did not schedule on main loop"

    def test_raises_when_no_main_loop_set(self):
        """When called from non-asyncio thread with no loop stored, raises RuntimeError."""
        import backend.services.desk_coordinator as dc

        # Ensure no main loop is stored
        original_loop = dc._main_loop
        dc._main_loop = None

        try:
            async def dummy():
                pass

            error_raised = threading.Event()

            def thread_target():
                try:
                    dc._run_async(dummy())
                except RuntimeError:
                    error_raised.set()

            t = threading.Thread(target=thread_target)
            t.start()
            t.join(timeout=5)

            assert error_raised.is_set(), (
                "Expected RuntimeError when _run_async called from non-asyncio "
                "thread without main loop stored"
            )
        finally:
            dc._main_loop = original_loop


# ---------------------------------------------------------------------------
# EventBus publishing tests (SR-002)
# ---------------------------------------------------------------------------


class TestDeskCoordinatorEventPublish:
    """Verify desk_coordinator._on_serial publishes to EventBus.

    SR-002: The ws_event_bridge exists but zero production code publishes
    to EventBus. desk_coordinator._on_serial must publish events instead
    of directly calling room.broadcast / room.send_to_seat.
    """

    def test_on_serial_seat_occupied_publishes_to_event_bus(self):
        """_on_serial with 'seat_occupied' publishes to EventBus."""
        from backend.services.desk_coordinator import desk

        desk.register_seat(1, 42)
        received = []

        def handler(event):
            received.append(event)

        event_bus.subscribe("seat_occupied", handler)
        try:
            desk._on_serial(1, {"type": "seat_occupied"})
            # Clean up the checkin prompt timer immediately
            desk._cancel_checkin_prompt(1)

            assert len(received) == 1, (
                f"Expected 1 seat_occupied event, got {len(received)}"
            )
            evt = received[0]
            assert evt.name == "seat_occupied"
            assert evt.payload["meeting_id"] == 42
            assert evt.payload["seat_id"] == 1
            assert "phase" in evt.payload
        finally:
            event_bus.unsubscribe("seat_occupied", handler)
            desk.unregister_seat(1)

    def test_on_serial_seat_vacant_publishes_to_event_bus(self):
        """_on_serial with 'seat_vacant' publishes to EventBus."""
        from backend.services.desk_coordinator import desk

        desk.register_seat(2, 99)
        received = []

        def handler(event):
            received.append(event)

        event_bus.subscribe("seat_vacant", handler)
        try:
            desk._on_serial(2, {"type": "seat_vacant"})

            assert len(received) == 1, (
                f"Expected 1 seat_vacant event, got {len(received)}"
            )
            evt = received[0]
            assert evt.name == "seat_vacant"
            assert evt.payload["meeting_id"] == 99
            assert evt.payload["seat_id"] == 2
            assert "phase" in evt.payload
        finally:
            event_bus.unsubscribe("seat_vacant", handler)
            desk.unregister_seat(2)


# ---------------------------------------------------------------------------
# Public async method EventBus publishing tests (CR-006)
# ---------------------------------------------------------------------------


class TestDeskCoordinatorPublicMethodsPublish:
    """Verify desk_coordinator public async methods publish to EventBus.

    CR-006: desk_coordinator public methods (on_vote_start, on_meeting_end, etc.)
    must publish events via EventBus instead of directly calling room.broadcast().
    """

    def test_on_speaker_seat_publishes_speaker_seat_set(self):
        """on_speaker_seat publishes speaker_seat_set to EventBus."""
        from backend.services.desk_coordinator import desk

        received = []

        def handler(event):
            received.append(event)

        event_bus.subscribe("speaker_seat_set", handler)
        try:
            asyncio.run(desk.on_speaker_seat(42, 3))
            assert len(received) == 1
            evt = received[0]
            assert evt.name == "speaker_seat_set"
            assert evt.payload["meeting_id"] == 42
            assert evt.payload["seat_id"] == 3
        finally:
            event_bus.unsubscribe("speaker_seat_set", handler)

    def test_on_speaker_clear_publishes_speaker_seat_clear(self):
        """on_speaker_clear publishes speaker_seat_clear to EventBus."""
        from backend.services.desk_coordinator import desk

        received = []

        def handler(event):
            received.append(event)

        event_bus.subscribe("speaker_seat_clear", handler)
        try:
            asyncio.run(desk.on_speaker_clear(42))
            assert len(received) == 1
            evt = received[0]
            assert evt.name == "speaker_seat_clear"
            assert evt.payload["meeting_id"] == 42
        finally:
            event_bus.unsubscribe("speaker_seat_clear", handler)

    def test_on_meeting_end_publishes_meeting_ended(self):
        """on_meeting_end publishes meeting_ended to EventBus."""
        from backend.services.desk_coordinator import desk

        received = []

        def handler(event):
            received.append(event)

        event_bus.subscribe("meeting_ended", handler)
        try:
            asyncio.run(desk.on_meeting_end(99))
            assert len(received) == 1
            evt = received[0]
            assert evt.name == "meeting_ended"
            assert evt.payload["meeting_id"] == 99
        finally:
            event_bus.unsubscribe("meeting_ended", handler)

    def test_on_translation_result_publishes_translation_final(self):
        """on_translation_result publishes translation_final to EventBus."""
        from backend.services.desk_coordinator import desk

        received = []

        def handler(event):
            received.append(event)

        event_bus.subscribe("translation_final", handler)
        try:
            asyncio.run(desk.on_translation_result(42, "你好", "Hello", 5, 100))
            assert len(received) == 1
            evt = received[0]
            assert evt.name == "translation_final"
            assert evt.payload["meeting_id"] == 42
            assert evt.payload["zh"] == "你好"
            assert evt.payload["en"] == "Hello"
            assert evt.payload["seat_id"] == 5
            assert evt.payload["segment_id"] == 100
            assert evt.payload["is_final"] is True
        finally:
            event_bus.unsubscribe("translation_final", handler)

    def test_on_service_call_publishes_service_call_created(self):
        """on_service_call publishes service_call_created to EventBus."""
        from backend.services.desk_coordinator import desk

        received = []

        def handler(event):
            received.append(event)

        event_bus.subscribe("service_call_created", handler)
        try:
            asyncio.run(desk.on_service_call(42, 3))
            assert len(received) == 1
            evt = received[0]
            assert evt.name == "service_call_created"
            assert evt.payload["meeting_id"] == 42
            assert evt.payload["seat_id"] == 3
        finally:
            event_bus.unsubscribe("service_call_created", handler)

    def test_on_vote_start_publishes_vote_started(self):
        """on_vote_start publishes vote_started to EventBus."""
        from backend.services.desk_coordinator import desk

        received = []

        def handler(event):
            received.append(event)

        event_bus.subscribe("vote_started", handler)
        try:
            asyncio.run(desk.on_vote_start(42, 7))
            assert len(received) == 1
            evt = received[0]
            assert evt.name == "vote_started"
            assert evt.payload["meeting_id"] == 42
            assert evt.payload["vote_id"] == 7
        finally:
            event_bus.unsubscribe("vote_started", handler)

    def test_on_vote_close_publishes_vote_closed(self):
        """on_vote_close publishes vote_closed to EventBus."""
        from backend.services.desk_coordinator import desk

        received = []

        def handler(event):
            received.append(event)

        event_bus.subscribe("vote_closed", handler)
        try:
            asyncio.run(desk.on_vote_close(42))
            assert len(received) == 1
            evt = received[0]
            assert evt.name == "vote_closed"
            assert evt.payload["meeting_id"] == 42
        finally:
            event_bus.unsubscribe("vote_closed", handler)
