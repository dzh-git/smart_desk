"""Business-event to per-seat lighting state resolver.

The manager keeps a durable base mode (idle / meeting / agenda) and independent
temporary overlays.  Effective mode is derived from priority, so an expiring
timer can no longer restore a stale mode over a newer event.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from backend.events import event_bus
from backend.events.base_event import BaseEvent
from backend.hardware.lighting_modes import LightingMode

logger = logging.getLogger(__name__)

MEETING_ENDED_IDLE_DELAY = 4.0
WELCOME_DURATION = 5.0
SERVICE_CALL_DURATION = 10.0
VOTE_OPEN_DURATION = 10.0
VOTE_CLOSED_DURATION = 10.0

_OVERLAY_PRIORITY = ("error", "service", "vote", "speaking", "welcome")


class LightingManager:
    """Resolve business state to an intended lighting mode for every seat."""

    def __init__(self, gateway, demo_seat_id: Optional[int] = None) -> None:
        self.gateway = gateway
        self.seat_ids: list[int] = list(gateway.seat_ids)
        self.demo_seat_id = demo_seat_id
        self.base_mode: dict[int, str] = {sid: "IDLE" for sid in self.seat_ids}
        self.overlays: dict[int, dict[str, str]] = {
            sid: {} for sid in self.seat_ids
        }
        # Public compatibility field: intended/effective mode.
        self.seat_mode: dict[int, str] = {sid: "IDLE" for sid in self.seat_ids}
        self._timers: dict[tuple[int, str], threading.Timer] = {}
        self._welcomed_seats: set[int] = set()
        self._subscriptions: list[tuple[str, object]] = []
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        self._subscriptions = [
            ("meeting_started", self._on_meeting_started),
            ("meeting_ended", self._on_meeting_ended),
            ("agenda_updated", self._on_agenda_updated),
            ("vote_started", self._on_vote_started),
            ("vote_closed", self._on_vote_closed),
            ("seat_occupied", self._on_seat_occupied),
            ("seat_vacant", self._on_seat_vacant),
            ("service_call_created", self._on_service_call_created),
            ("service_call_resolved", self._on_service_call_finished),
            ("service_call_cancelled", self._on_service_call_finished),
            ("speaker_speaking", self._on_speaker_speaking),
            ("speaker_speaking_stop", self._on_speaker_speaking_stop),
        ]
        for event_name, handler in self._subscriptions:
            event_bus.subscribe(event_name, handler)

        managers = getattr(self.gateway, "seat_managers", None)
        if managers:
            for sid, manager in managers.items():
                if getattr(manager, "pir_callback", None) is None:
                    manager.pir_callback = (
                        lambda occupied, _sid=sid: self._on_pir_for_seat(_sid, occupied)
                    )
                manager.connection_callback = (
                    lambda connected, _sid=sid: self._on_connection(_sid, connected)
                )
        self._registered = True
        logger.info("[Lighting] registered handlers for seats=%s", self.seat_ids)

    def unregister(self) -> None:
        """Release EventBus handlers and timers for tests/app replacement."""
        if not self._registered:
            return
        for event_name, handler in self._subscriptions:
            event_bus.unsubscribe(event_name, handler)
        self._subscriptions.clear()
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        self._registered = False

    def _active_seats(self) -> list[int]:
        if self.demo_seat_id is not None:
            return [self.demo_seat_id]
        return self.seat_ids

    def _is_active_seat(self, seat_id: int) -> bool:
        return self.demo_seat_id is None or seat_id == self.demo_seat_id

    def set_mode(self, seat_id: int, mode: str, *, force: bool = False) -> bool:
        mode = mode.upper()
        if not LightingMode.is_valid(mode):
            logger.error("[Lighting] invalid mode %r for seat %s", mode, seat_id)
            return False
        if not force and self.seat_mode.get(seat_id) == mode:
            return True
        self.seat_mode[seat_id] = mode
        sent = bool(self.gateway.send(seat_id, "SET_MODE", mode))
        if not sent:
            logger.warning(
                "[Lighting] command pending/offline seat=%s intended=%s", seat_id, mode,
            )
        return sent

    def set_mode_all(self, mode: str, *, force: bool = False) -> None:
        for seat_id in self._active_seats():
            self.set_mode(seat_id, mode, force=force)

    def _effective_mode(self, seat_id: int) -> str:
        seat_overlays = self.overlays.setdefault(seat_id, {})
        for key in _OVERLAY_PRIORITY:
            if key in seat_overlays:
                return seat_overlays[key]
        return self.base_mode.get(seat_id, "IDLE")

    def _render(self, seat_id: int, *, force: bool = False) -> None:
        if self._is_active_seat(seat_id):
            self.set_mode(seat_id, self._effective_mode(seat_id), force=force)

    def _set_base(self, seat_id: int, mode: str) -> None:
        self.base_mode[seat_id] = mode
        self._render(seat_id)

    def _set_overlay(
        self, seat_id: int, key: str, mode: str, duration: float | None = None,
    ) -> None:
        self._cancel_timer(seat_id, key)
        self.overlays.setdefault(seat_id, {})[key] = mode
        self._render(seat_id)
        if duration is not None:
            self._schedule(seat_id, key, duration, self._clear_overlay)

    def _clear_overlay(self, seat_id: int, key: str) -> None:
        self._timers.pop((seat_id, key), None)
        self.overlays.setdefault(seat_id, {}).pop(key, None)
        self._render(seat_id)

    def _clear_seat_transients(self, seat_id: int) -> None:
        for timer_key in [key for key in self._timers if key[0] == seat_id]:
            timer = self._timers.pop(timer_key)
            timer.cancel()
        self.overlays.setdefault(seat_id, {}).clear()

    def _on_meeting_started(self, event: BaseEvent) -> None:
        self._welcomed_seats.clear()
        for seat_id in self._active_seats():
            self._clear_seat_transients(seat_id)
            self.base_mode[seat_id] = "MEETING_ACTIVE"
            self._render(seat_id)

    def _on_meeting_ended(self, event: BaseEvent) -> None:
        for seat_id in self._active_seats():
            self._clear_seat_transients(seat_id)
            self.base_mode[seat_id] = "MEETING_ENDED"
            self._render(seat_id)
            self._schedule(seat_id, "base_end", MEETING_ENDED_IDLE_DELAY, self._idle_after_end)

    def _idle_after_end(self, seat_id: int, key: str) -> None:
        self._timers.pop((seat_id, key), None)
        self.base_mode[seat_id] = "IDLE"
        self._render(seat_id)

    def _on_agenda_updated(self, event: BaseEvent) -> None:
        mode = (
            "AGENDA_ACTIVE"
            if event.payload.get("current_agenda_id") is not None
            else "MEETING_ACTIVE"
        )
        for seat_id in self._active_seats():
            self._set_base(seat_id, mode)

    def _on_vote_started(self, event: BaseEvent) -> None:
        for seat_id in self._active_seats():
            self._set_overlay(seat_id, "vote", "VOTE_OPEN", VOTE_OPEN_DURATION)

    def _on_vote_closed(self, event: BaseEvent) -> None:
        for seat_id in self._active_seats():
            self._set_overlay(seat_id, "vote", "VOTE_CLOSED", VOTE_CLOSED_DURATION)

    def _on_seat_occupied(self, event: BaseEvent) -> None:
        seat_id = self._seat_of(event)
        if seat_id is not None:
            self._play_welcome(seat_id)

    def _play_welcome(self, seat_id: int) -> None:
        if not self._is_active_seat(seat_id):
            return
        if self._effective_mode(seat_id) != "IDLE" or seat_id in self._welcomed_seats:
            return
        self._welcomed_seats.add(seat_id)
        self._set_overlay(seat_id, "welcome", "WELCOME", WELCOME_DURATION)

    def _on_pir_for_seat(self, seat_id: int, occupied: bool) -> None:
        if occupied:
            self._play_welcome(seat_id)

    def _on_seat_vacant(self, event: BaseEvent) -> None:
        seat_id = self._seat_of(event)
        if seat_id is None or not self._is_active_seat(seat_id):
            return
        self._clear_seat_transients(seat_id)
        self.base_mode[seat_id] = "IDLE"
        self._render(seat_id)

    def _on_service_call_created(self, event: BaseEvent) -> None:
        seat_id = self._seat_of(event)
        if seat_id is not None and self._is_active_seat(seat_id):
            self._set_overlay(
                seat_id, "service", "SERVICE_CALL", SERVICE_CALL_DURATION,
            )

    def _on_service_call_finished(self, event: BaseEvent) -> None:
        seat_id = self._seat_of(event)
        if seat_id is not None and self._is_active_seat(seat_id):
            self._clear_overlay(seat_id, "service")

    def _on_speaker_speaking(self, event: BaseEvent) -> None:
        seat_id = self._seat_of(event)
        if seat_id is not None and self._is_active_seat(seat_id):
            self._set_overlay(seat_id, "speaking", "AI_SPEAKING")

    def _on_speaker_speaking_stop(self, event: BaseEvent) -> None:
        seat_id = self._seat_of(event)
        if seat_id is not None and self._is_active_seat(seat_id):
            self._clear_overlay(seat_id, "speaking")

    def _on_connection(self, seat_id: int, connected: bool) -> None:
        if connected and self._is_active_seat(seat_id):
            # Arduino resets to IDLE when its serial port opens. Re-assert the
            # intended state after every reconnect.
            self._render(seat_id, force=True)

    @staticmethod
    def _seat_of(event: BaseEvent) -> Optional[int]:
        value = event.payload.get("seat_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _cancel_timer(self, seat_id: int, key: str) -> None:
        timer = self._timers.pop((seat_id, key), None)
        if timer is not None:
            timer.cancel()

    def _schedule(self, seat_id: int, key: str, delay: float, callback) -> None:
        self._cancel_timer(seat_id, key)
        timer_key = (seat_id, key)

        def fire() -> None:
            # A cancelled timer can already be entering its callback.  Only
            # the newest timer for this state key may mutate the resolver.
            if self._timers.get(timer_key) is timer:
                callback(seat_id, key)

        timer = threading.Timer(delay, fire)
        timer.daemon = True
        self._timers[timer_key] = timer
        timer.start()
