"""
LightingManager — maps business events to Arduino lighting commands.

Subscribes to EventBus events and translates them into ``SET_MODE`` commands
via ArduinoManager. PIR edge events are pushed from ArduinoManager (not the
EventBus) and drive the WELCOME welcome animation only while idle, per
protocol.md §4.3.

Event → mode mapping (integration plan Phase 4):
    meeting_started        -> MEETING_ACTIVE
    meeting_ended          -> MEETING_ENDED, then auto IDLE after a delay
    agenda_updated         -> AGENDA_ACTIVE
    vote_started           -> VOTE_OPEN
    vote_closed            -> MEETING_ACTIVE
    service_call_created   -> SERVICE_CALL
    PIR rising (idle)      -> WELCOME (one-shot; firmware auto-returns IDLE)

Per protocol.md §4.3, WELCOME is a one-shot animation that the firmware plays
(~1.6 s) and then auto-reverts to IDLE. The PIR falling edge (EVENT PIR 0) is
no longer used to drive lighting; it remains only as occupancy sensing.
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


class LightingManager:
    """Bridges EventBus business events to lighting commands."""

    def __init__(self, arduino) -> None:
        self.arduino = arduino
        self.current_mode = "IDLE"
        self._registered = False

    # ── Wiring ──────────────────────────────────────────────────────────────

    def register(self) -> None:
        """Subscribe to EventBus events. Idempotent (safe under --reload)."""
        if self._registered:
            return
        event_bus.subscribe("meeting_started", self._on_meeting_started)
        event_bus.subscribe("meeting_ended", self._on_meeting_ended)
        event_bus.subscribe("agenda_updated", self._on_agenda_updated)
        event_bus.subscribe("vote_started", self._on_vote_started)
        event_bus.subscribe("vote_closed", self._on_vote_closed)
        event_bus.subscribe("service_call_created", self._on_service_call_created)
        # PIR edge events arrive from ArduinoManager, not the EventBus.
        if self.arduino.pir_callback is None:
            self.arduino.pir_callback = self._on_pir
        self._registered = True
        logger.info("[Lighting] registered EventBus handlers")

    # ── Command helper ──────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        self.current_mode = mode
        self.arduino.send_command("SET_MODE", mode)

    # ── EventBus handlers ───────────────────────────────────────────────────

    def _on_meeting_started(self, event: BaseEvent) -> None:
        self.set_mode("MEETING_ACTIVE")

    def _on_meeting_ended(self, event: BaseEvent) -> None:
        self.set_mode("MEETING_ENDED")
        self._schedule_idle(MEETING_ENDED_IDLE_DELAY)

    def _on_agenda_updated(self, event: BaseEvent) -> None:
        self.set_mode("AGENDA_ACTIVE")

    def _on_vote_started(self, event: BaseEvent) -> None:
        self.set_mode("VOTE_OPEN")

    def _on_vote_closed(self, event: BaseEvent) -> None:
        self.set_mode("MEETING_ACTIVE")

    def _on_service_call_created(self, event: BaseEvent) -> None:
        self.set_mode("SERVICE_CALL")

    # ── PIR edge handler (from ArduinoManager) ──────────────────────────────

    def _on_pir(self, occupied: bool) -> None:
        # Only welcome while idle; ignore otherwise. EVENT PIR 0 is intentionally
        # ignored — the firmware auto-reverts WELCOME to IDLE (protocol.md §4.3).
        if occupied and self.current_mode == "IDLE":
            self.set_mode("WELCOME")

    # ── Timers ──────────────────────────────────────────────────────────────

    def _schedule_idle(self, delay: float) -> None:
        t = threading.Timer(delay, self._revert_idle)
        t.daemon = True
        t.start()

    def _revert_idle(self) -> None:
        if self.current_mode == "MEETING_ENDED":
            self.set_mode("IDLE")
