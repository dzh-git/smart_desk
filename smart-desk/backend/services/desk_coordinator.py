"""
Desk coordinator — central brain wiring serial, WebSocket, and business logic.
Cross-platform: asyncio.run() bridges serial thread → async WS on both Windows/Linux.
Hardware-decoupled: all hardware I/O goes through serial_svc (stub when no Arduino).
"""
from __future__ import annotations
import asyncio
import threading
from backend.services.serial_service import serial_svc
from backend.services.ws_service import ws_svc
from backend.services.business_logic import DeskStateMachine


def _run_async(coro):
    """Run coroutine from non-async thread. Cross-platform safe."""
    try:
        loop = asyncio.get_running_loop()
        # Already in async context — shouldn't happen from serial thread,
        # but handle gracefully by creating a task on the current loop
        asyncio.ensure_future(coro)
    except RuntimeError:
        # No running loop (serial thread) — create one
        asyncio.run(coro)


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
        room = ws_svc.get_or_create(self._seat_meeting.get(seat_id, 1))

        if msg_type == "seat_occupied":
            s = self.state.seat_occupied(seat_id)
            # Hardware → LED (stubbed when no Arduino)
            serial_svc.set_led(seat_id, s.led_pattern, s.led_color)
            # Broadcast to all tablets
            _run_async(room.broadcast({
                "type": "seat_occupied",
                "payload": {"seat_id": seat_id, "phase": s.phase.value},
            }))
            # Auto checkin prompt after 3s
            self._schedule_checkin_prompt(seat_id, room)

        elif msg_type == "seat_vacant":
            s = self.state.seat_vacant(seat_id)
            serial_svc.set_led(seat_id, s.led_pattern, s.led_color)
            self._cancel_checkin_prompt(seat_id)
            _run_async(room.broadcast({
                "type": "seat_vacant",
                "payload": {"seat_id": seat_id, "phase": s.phase.value},
            }))

    # ── Auto checkin prompt (3s delay after TOF detection) ──

    def _schedule_checkin_prompt(self, seat_id: int, room):
        self._cancel_checkin_prompt(seat_id)
        def send():
            _run_async(room.send_to_seat(seat_id, {
                "type": "checkin_prompt",
                "payload": {"seat_id": seat_id},
            }))
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
        room = ws_svc.get_or_create(meeting_id)
        for s in self.state.seats.values():
            if s.phase.value != "empty":
                serial_svc.set_led(s.seat_id, "solid", (201, 168, 76))
        await room.broadcast({"type": "vote_update", "payload": {"vote_id": vote_id}})

    async def on_vote_close(self, meeting_id: int):
        """Reset LEDs to normal per-seat state after vote closes."""
        room = ws_svc.get_or_create(meeting_id)
        for s in self.state.seats.values():
            serial_svc.set_led(s.seat_id, s.led_pattern, s.led_color)
        await room.broadcast({"type": "vote_update", "payload": {}})

    async def on_meeting_end(self, meeting_id: int):
        """Reset all seats when meeting ends."""
        room = ws_svc.get_or_create(meeting_id)
        for s in self.state.seats.values():
            self.state.seat_vacant(s.seat_id)
            serial_svc.set_led(s.seat_id, "breathe", (255, 200, 150))
        await room.broadcast({"type": "meeting_ended", "payload": {}})

    async def on_service_call(self, meeting_id: int, seat_id: int):
        """Broadcast service call update to all tablets."""
        room = ws_svc.get_or_create(meeting_id)
        await room.broadcast({
            "type": "service_update",
            "payload": {"seat_id": seat_id},
        })

    async def on_speaker_seat(self, meeting_id: int, seat_id: int):
        """Broadcast speaker seat assignment + set LED to blue."""
        room = ws_svc.get_or_create(meeting_id)
        serial_svc.set_led(seat_id, "solid", (80, 140, 255))
        await room.broadcast({
            "type": "speaker_seat_set",
            "payload": {"seat_id": seat_id},
        })

    async def on_speaker_clear(self, meeting_id: int):
        """Clear speaker seat, reset LEDs."""
        room = ws_svc.get_or_create(meeting_id)
        for s in self.state.seats.values():
            serial_svc.set_led(s.seat_id, s.led_pattern, s.led_color)
        await room.broadcast({
            "type": "speaker_seat_clear",
            "payload": {},
        })

    async def on_translation_result(self, meeting_id: int, zh: str, en: str, seat_id: int):
        """Broadcast translation result to all tablets."""
        room = ws_svc.get_or_create(meeting_id)
        await room.broadcast({
            "type": "translation_result",
            "payload": {"zh": zh, "en": en, "seat_id": seat_id},
        })

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
