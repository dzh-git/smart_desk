"""
LightingManager — maps business events to per-seat lighting commands.

Transport-agnostic: it talks to a ``SeatGatewayLike`` gateway (either
``LocalSeatGateway`` for dev single-machine serial, or ``SeatGateway`` for
production distributed-over-WebSocket). The gateway decides HOW a command
reaches the seat's Arduino; this manager only decides WHAT command and to
WHICH seat.

Routing:
    * Global events (meeting / agenda / vote) are broadcast to ALL seats.
    * Seat-scoped events (occupy / vacant / service call / speaker speaking)
      are sent ONLY to the seat named in the event payload.

Event → mode mapping (integration plan Phase 4, plus per-seat extensions):
    meeting_started        -> MEETING_ACTIVE        (active seats)
    meeting_ended          -> MEETING_ENDED, then auto IDLE after a delay (active)
    agenda_updated         -> AGENDA_ACTIVE          (active seats)
    vote_started           -> VOTE_OPEN, auto-revert after 10s (active seats)
    vote_closed            -> VOTE_CLOSED, auto-revert to MEETING_ACTIVE after 10s
    seat_occupied          -> WELCOME  (one-shot) on that seat  [FIX 1]
    seat_vacant            -> IDLE on that seat
    service_call_created   -> SERVICE_CALL on that seat, auto-revert after 10s
                              [FIX 2]
    speaker_speaking       -> AI_SPEAKING on that seat [FIX 4]
    speaker_speaking_stop  -> revert that seat to its previous mode [FIX 4]

When ``demo_seat_id`` is set (single-strip demo mode), only that seat
receives lighting commands: global events light only it, and seat-scoped
events for other seats are silently ignored.

Per protocol.md §4.3, WELCOME is a one-shot animation the firmware plays and
then auto-reverts to IDLE, so we schedule a backend-side revert to the seat's
previous mode after the animation duration to keep state in sync.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from backend.events import event_bus
from backend.events.base_event import BaseEvent

logger = logging.getLogger(__name__)

# meeting_ended -> MEETING_ENDED, then auto back to IDLE after this delay (s).
MEETING_ENDED_IDLE_DELAY = 4.0

# WELCOME one-shot animation duration (s) — matches firmware (~5s per 灯光变化表).
WELCOME_DURATION = 5.0

# Service call flashing lifetime (s) — user requirement: 10s then revert.
SERVICE_CALL_DURATION = 10.0

# Vote open / closed flashing lifetime (s) — flash then revert, same pattern
# as SERVICE_CALL.
VOTE_OPEN_DURATION = 10.0
VOTE_CLOSED_DURATION = 10.0


class LightingManager:
    """Bridges EventBus business events to per-seat lighting commands."""

    def __init__(self, gateway, demo_seat_id: Optional[int] = None) -> None:
        self.gateway = gateway
        self.seat_ids: list[int] = list(gateway.seat_ids)
        # When set, only this seat responds to lighting commands (demo /
        # single-strip mode). None = broadcast to all seats (production).
        self.demo_seat_id = demo_seat_id
        # Per-seat current lighting mode (kept in sync for status reporting).
        self.seat_mode: dict[int, str] = {sid: "IDLE" for sid in self.seat_ids}
        # Per-seat revert timers (service call / meeting-ended / welcome).
        self._revert_timers: dict[int, threading.Timer] = {}
        # Per-seat mode that was active before AI_SPEAKING, for clean revert.
        self._ai_prev: dict[int, str] = {}
        # Seats that have already received WELCOME. Each seat gets WELCOME
        # exactly once per meeting cycle; re-sitting after the first time
        # does NOT replay the animation. Cleared on meeting_started.
        self._welcomed_seats: set[int] = set()
        self._registered = False

    # ── Wiring ──────────────────────────────────────────────────────────────

    def register(self) -> None:
        """Subscribe to EventBus events. Idempotent (safe under --reload)."""
        if self._registered:
            return
        # Global (broadcast to all seats)
        event_bus.subscribe("meeting_started", self._on_meeting_started)
        event_bus.subscribe("meeting_ended", self._on_meeting_ended)
        event_bus.subscribe("agenda_updated", self._on_agenda_updated)
        event_bus.subscribe("vote_started", self._on_vote_started)
        event_bus.subscribe("vote_closed", self._on_vote_closed)
        # Seat-scoped
        event_bus.subscribe("seat_occupied", self._on_seat_occupied)
        event_bus.subscribe("seat_vacant", self._on_seat_vacant)
        event_bus.subscribe("service_call_created", self._on_service_call_created)
        event_bus.subscribe("speaker_speaking", self._on_speaker_speaking)
        event_bus.subscribe("speaker_speaking_stop", self._on_speaker_speaking_stop)
        # Firmware-side occupancy (central/dev mode only): each Nano reports
        # EVENT PIR on its own serial line. Bind a per-seat callback so a PIR
        # rising edge also plays WELCOME. In distributed mode occupancy arrives
        # via the seat WebSocket uplink -> EventBus, so no callback is needed.
        seat_managers = getattr(self.gateway, "seat_managers", None)
        if seat_managers:
            for sid, mgr in seat_managers.items():
                if not self._is_active_seat(sid):
                    continue
                if getattr(mgr, "pir_callback", None) is None:
                    mgr.pir_callback = lambda occ, _sid=sid: self._on_pir_for_seat(_sid, occ)
        self._registered = True
        logger.info("[Lighting] registered EventBus handlers (seats=%s)", self.seat_ids)

    # ── Command helpers ─────────────────────────────────────────────────────

    def _active_seats(self) -> list[int]:
        """Seats that should receive lighting commands.

        In demo mode (``demo_seat_id`` set) only that seat is active; otherwise
        all seats are active (production broadcast).
        """
        if self.demo_seat_id is not None:
            return [self.demo_seat_id]
        return self.seat_ids

    def _is_active_seat(self, seat_id: int) -> bool:
        """Whether a seat-scoped event should trigger lighting on this seat."""
        return self.demo_seat_id is None or seat_id == self.demo_seat_id

    def set_mode(self, seat_id: int, mode: str) -> None:
        """Send ``SET_MODE <mode>`` to one seat and record its mode."""
        self.seat_mode[seat_id] = mode
        ok = self.gateway.send(seat_id, "SET_MODE", mode)
        if not ok:
            logger.debug(
                "[Lighting] SET_MODE %s -> seat %s not sent (offline/disabled)",
                mode, seat_id,
            )

    def set_mode_all(self, mode: str) -> None:
        """Broadcast a mode to every active seat."""
        for seat_id in self._active_seats():
            self.set_mode(seat_id, mode)

    # ── EventBus handlers: global ───────────────────────────────────────────

    def _on_meeting_started(self, event: BaseEvent) -> None:
        # Reset WELCOME tracking: each new meeting cycle allows one WELCOME
        # per seat again.
        self._welcomed_seats.clear()
        self.set_mode_all("MEETING_ACTIVE")

    def _on_meeting_ended(self, event: BaseEvent) -> None:
        self.set_mode_all("MEETING_ENDED")
        for seat_id in self._active_seats():
            self._schedule_revert(seat_id, MEETING_ENDED_IDLE_DELAY, "IDLE")

    def _on_agenda_updated(self, event: BaseEvent) -> None:
        self.set_mode_all("AGENDA_ACTIVE")

    def _on_vote_started(self, event: BaseEvent) -> None:
        for seat_id in self._active_seats():
            prev = self.seat_mode.get(seat_id, "MEETING_ACTIVE")
            self.set_mode(seat_id, "VOTE_OPEN")
            self._schedule_revert(seat_id, VOTE_OPEN_DURATION, prev)

    def _on_vote_closed(self, event: BaseEvent) -> None:
        for seat_id in self._active_seats():
            self.set_mode(seat_id, "VOTE_CLOSED")
            self._schedule_revert(seat_id, VOTE_CLOSED_DURATION, "MEETING_ACTIVE")

    # ── EventBus handlers: seat-scoped ──────────────────────────────────────

    def _on_seat_occupied(self, event: BaseEvent) -> None:
        """FIX 1: play the WELCOME animation on the seat that just got occupied."""
        seat_id = self._seat_of(event)
        if seat_id is None or not self._is_active_seat(seat_id):
            return
        self._play_welcome(seat_id)

    def _play_welcome(self, seat_id: int) -> None:
        """Play the one-shot WELCOME animation on a seat (FIX 1).

        Used by both the app-level ``seat_occupied`` event and the firmware's
        ``EVENT PIR`` callback (central mode). The firmware auto-reverts WELCOME
        to IDLE, so we also schedule a backend-side revert after the animation
        duration to keep ``seat_mode`` accurate for the status panel (and avoid
        the old bug where current_mode got stuck on WELCOME and suppressed
        later triggers).

        Each seat receives WELCOME at most once per meeting cycle. After the
        first WELCOME, subsequent occupancy/PIR triggers for that seat are
        silently skipped. The set is cleared on ``meeting_started``.

        Per protocol §4.3, WELCOME is only played when the current mode is
        ``IDLE``. In any other mode (MEETING_ACTIVE, SERVICE_CALL, VOTE_OPEN,
        etc.) the trigger is silently ignored — this prevents WELCOME from
        cancelling an active revert timer (e.g. the 10s SERVICE_CALL revert)
        and leaving the seat stuck in a transient mode forever.
        """
        if not self._is_active_seat(seat_id):
            return
        # Only play WELCOME in IDLE mode (protocol §4.3). This also prevents
        # _schedule_revert from cancelling an ongoing transient's revert timer.
        if self.seat_mode.get(seat_id, "IDLE") != "IDLE":
            logger.debug(
                "[Lighting] WELCOME skipped for seat %d (current mode=%s, not IDLE)",
                seat_id, self.seat_mode.get(seat_id),
            )
            return
        if seat_id in self._welcomed_seats:
            logger.debug(
                "[Lighting] WELCOME skipped for seat %d (already welcomed this meeting)",
                seat_id,
            )
            return
        self._welcomed_seats.add(seat_id)

        prev = self.seat_mode.get(seat_id, "IDLE")
        self.set_mode(seat_id, "WELCOME")
        self._schedule_revert(seat_id, WELCOME_DURATION, prev)

    def _on_pir_for_seat(self, seat_id: int, occupied: bool) -> None:
        """Firmware EVENT PIR callback (per seat, central mode). Only the rising
        edge drives the WELCOME animation; the falling edge is occupancy-only
        (protocol §4.3)."""
        if occupied:
            self._play_welcome(seat_id)

    def _on_seat_vacant(self, event: BaseEvent) -> None:
        seat_id = self._seat_of(event)
        if seat_id is None or not self._is_active_seat(seat_id):
            return
        self._cancel_timer(seat_id)
        self.set_mode(seat_id, "IDLE")

    def _on_service_call_created(self, event: BaseEvent) -> None:
        """FIX 2: flash SERVICE_CALL on the calling seat, revert after 10s."""
        seat_id = self._seat_of(event)
        if seat_id is None or not self._is_active_seat(seat_id):
            logger.warning("[Lighting] service_call_created without seat_id or inactive seat")
            return
        prev = self.seat_mode.get(seat_id, "IDLE")
        self.set_mode(seat_id, "SERVICE_CALL")
        self._schedule_revert(seat_id, SERVICE_CALL_DURATION, prev)

    def _on_speaker_speaking(self, event: BaseEvent) -> None:
        """FIX 4: light AI_SPEAKING on the speaking seat."""
        seat_id = self._seat_of(event)
        if seat_id is None or not self._is_active_seat(seat_id):
            return
        prev = self._ai_prev.get(seat_id, self.seat_mode.get(seat_id, "IDLE"))
        self._ai_prev[seat_id] = prev
        self.set_mode(seat_id, "AI_SPEAKING")

    def _on_speaker_speaking_stop(self, event: BaseEvent) -> None:
        seat_id = self._seat_of(event)
        if seat_id is None or not self._is_active_seat(seat_id):
            return
        prev = self._ai_prev.pop(seat_id, "IDLE")
        self.set_mode(seat_id, prev)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _seat_of(event: BaseEvent) -> Optional[int]:
        seat_id = event.payload.get("seat_id")
        return int(seat_id) if seat_id is not None else None

    def _cancel_timer(self, seat_id: int) -> None:
        timer = self._revert_timers.pop(seat_id, None)
        if timer is not None:
            timer.cancel()

    def _schedule_revert(self, seat_id: int, delay: float, mode: str) -> None:
        """Schedule a seat to revert to ``mode`` after ``delay`` seconds.

        Cancels any existing revert timer for that seat first, so the most
        recent event wins (e.g. a new service call extends/overrides a prior
        one on the same seat).
        """
        self._cancel_timer(seat_id)
        timer = threading.Timer(delay, self._revert, args=(seat_id, mode))
        timer.daemon = True
        self._revert_timers[seat_id] = timer
        timer.start()

    def _revert(self, seat_id: int, mode: str) -> None:
        self._revert_timers.pop(seat_id, None)
        self.set_mode(seat_id, mode)
