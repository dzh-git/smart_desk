"""
Desk coordinator — central brain wiring serial, WebSocket, and business logic.
Hardware-decoupled: all hardware I/O goes through serial_svc (stub when no Arduino).
"""
from __future__ import annotations
import asyncio
import threading
from backend.services.event_bus import event_bus, BaseEvent
from backend.services.serial_service import serial_svc
from backend.services.seat_state_machine import DeskStateMachine

# Reference to the main event loop captured at startup via set_main_loop().
# Used by _run_async to schedule WebSocket operations from non-asyncio threads
# (e.g. serial thread, threading.Timer callbacks) via
# asyncio.run_coroutine_threadsafe() instead of asyncio.run().
# WebSocket transports are bound to their accepting loop and cannot be
# used from a different loop — asyncio.run() silently loses messages.
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop():
    """Capture the main event loop for thread-safe WebSocket operations.

    Must be called from the main asyncio context (e.g. FastAPI lifespan)
    before any serial/hardware events fire. If no event loop is running,
    _main_loop stays None and _run_async will raise a RuntimeError when
    called from a non-asyncio thread.
    """
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        _main_loop = None


def _run_async(coro):
    """Schedule a coroutine for execution, thread-safe.

    - If called from the event loop thread: uses asyncio.ensure_future
      (fire-and-forget).
    - If called from another thread: uses asyncio.run_coroutine_threadsafe()
      with the stored main loop to safely cross the thread boundary.
    """
    try:
        loop = asyncio.get_running_loop()
        asyncio.ensure_future(coro)
    except RuntimeError:
        if _main_loop is None:
            raise RuntimeError(
                "DeskCoordinator not initialized: no main loop stored. "
                "Call set_main_loop() during startup."
            )
        asyncio.run_coroutine_threadsafe(coro, _main_loop)


class DeskCoordinator:
    """Singleton bridging: hardware events ↔ state machine ↔ WebSocket ↔ LED output."""

    def __init__(self):
        self.state = DeskStateMachine()
        self._seat_meeting: dict[int, int] = {}   # seat_id → meeting_id
        self._pending_checkins: dict[int, threading.Timer] = {}

    # ── Seat → Meeting mapping ──

    def register_seat(self, seat_id: int, meeting_id: int):
        """Called when a tablet WebSocket connects."""
        self._seat_meeting[seat_id] = meeting_id

    def unregister_seat(self, seat_id: int):
        """Called when a tablet WebSocket disconnects."""
        self._seat_meeting.pop(seat_id, None)
        self._cancel_checkin_prompt(seat_id)

    # ── Serial → WS bridge (called from serial thread) ──

    def _on_serial(self, seat_id: int, msg: dict):
        """Callback registered with serial_svc. Runs in serial thread."""
        msg_type = msg.get("type", "")
        meeting_id = self._seat_meeting.get(seat_id, 1)

        if msg_type == "seat_occupied":
            s = self.state.seat_occupied(seat_id)
            # Hardware → LED (stubbed when no Arduino)
            serial_svc.set_led(seat_id, s.led_pattern, s.led_color)
            # Publish to EventBus → ws_event_bridge handles WebSocket broadcast
            event_bus.publish(BaseEvent(
                name="seat_occupied",
                payload={"meeting_id": meeting_id, "seat_id": seat_id, "phase": s.phase.value},
            ))
            # Auto checkin prompt after 3s
            self._schedule_checkin_prompt(seat_id, meeting_id)

        elif msg_type == "seat_vacant":
            s = self.state.seat_vacant(seat_id)
            serial_svc.set_led(seat_id, s.led_pattern, s.led_color)
            self._cancel_checkin_prompt(seat_id)
            event_bus.publish(BaseEvent(
                name="seat_vacant",
                payload={"meeting_id": meeting_id, "seat_id": seat_id, "phase": s.phase.value},
            ))

    # ── Auto checkin prompt (3s delay after TOF detection) ──

    def _schedule_checkin_prompt(self, seat_id: int, meeting_id: int):
        self._cancel_checkin_prompt(seat_id)
        def send():
            event_bus.publish(BaseEvent(
                name="checkin_prompt",
                payload={"meeting_id": meeting_id, "seat_id": seat_id},
            ))
        timer = threading.Timer(3.0, send)
        timer.start()
        self._pending_checkins[seat_id] = timer

    def _cancel_checkin_prompt(self, seat_id: int):
        timer = self._pending_checkins.pop(seat_id, None)
        if timer:
            timer.cancel()

    # ── Public API (called from async FastAPI context) ──

    async def on_checkin(self, meeting_id: int, seat_id: int):
        """Called after REST checkin — update state machine + LED."""
        s = self.state.check_in(seat_id, seat_id, name="")
        self._cancel_checkin_prompt(seat_id)
        serial_svc.set_led(seat_id, s.led_pattern, s.led_color)

    async def on_vote_start(self, meeting_id: int, vote_id: int):
        """Set occupied seats' LEDs to gold during voting."""
        for s in self.state.seats.values():
            if s.phase.value != "empty":
                serial_svc.set_led(s.seat_id, "solid", (201, 168, 76))
        event_bus.publish(BaseEvent(
            name="vote_started",
            payload={"meeting_id": meeting_id, "vote_id": vote_id},
        ))

    async def on_vote_close(self, meeting_id: int):
        """Reset LEDs to normal per-seat state after vote closes."""
        for s in self.state.seats.values():
            serial_svc.set_led(s.seat_id, s.led_pattern, s.led_color)
        event_bus.publish(BaseEvent(
            name="vote_closed",
            payload={"meeting_id": meeting_id},
        ))

    async def on_meeting_end(self, meeting_id: int):
        """Reset all seats when meeting ends."""
        for s in self.state.seats.values():
            self.state.seat_vacant(s.seat_id)
            serial_svc.set_led(s.seat_id, "breathe", (255, 200, 150))
        event_bus.publish(BaseEvent(
            name="meeting_ended",
            payload={"meeting_id": meeting_id},
        ))

    async def on_service_call(self, meeting_id: int, seat_id: int):
        """Broadcast service call update to all tablets."""
        event_bus.publish(BaseEvent(
            name="service_call_created",
            payload={"meeting_id": meeting_id, "seat_id": seat_id},
        ))

    async def on_speaker_seat(self, meeting_id: int, seat_id: int):
        """Broadcast speaker seat assignment + set LED to blue."""
        serial_svc.set_led(seat_id, "solid", (80, 140, 255))
        event_bus.publish(BaseEvent(
            name="speaker_seat_set",
            payload={"meeting_id": meeting_id, "seat_id": seat_id},
        ))

    async def on_speaker_clear(self, meeting_id: int):
        """Clear speaker seat, reset LEDs."""
        for s in self.state.seats.values():
            serial_svc.set_led(s.seat_id, s.led_pattern, s.led_color)
        event_bus.publish(BaseEvent(
            name="speaker_seat_clear",
            payload={"meeting_id": meeting_id},
        ))

    async def on_translation_result(self, meeting_id: int, zh: str, en: str, seat_id: int, segment_id: int = 0):
        """Broadcast translation result to all tablets."""
        event_bus.publish(BaseEvent(
            name="translation_final",
            payload={
                "meeting_id": meeting_id, "zh": zh, "en": en,
                "seat_id": seat_id, "segment_id": segment_id,
                "is_final": True,
            },
        ))

    def get_seat_state(self, seat_id: int) -> dict:
        """Get current state of a seat (for debug / status queries)."""
        s = self.state.seats.get(seat_id)
        if not s:
            return {}
        return {
            "seat_id": s.seat_id,
            "phase": s.phase.value,
            "led_pattern": s.led_pattern,
            "led_color": list(s.led_color),
        }


# Singleton
desk = DeskCoordinator()

# Wire serial → coordinator callback (hardware events → state machine → WS)
serial_svc.on_message(desk._on_serial)
