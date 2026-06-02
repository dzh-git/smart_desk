from __future__ import annotations
from backend.services.event_bus import EventBus, BaseEvent


class ServiceCallError(Exception):
    """Base exception for service call errors."""
    pass


class ServiceCallNotFoundError(ServiceCallError):
    """Service call does not exist."""
    pass


class DuplicatePendingCallError(ServiceCallError):
    """A pending call already exists for this seat."""
    pass


class ServiceCallService:
    VALID_SERVICE_TYPES = {"coffee", "tea", "water", "other"}

    def __init__(self, event_bus: EventBus, service_call_repo):
        self.bus = event_bus
        self.repo = service_call_repo

    def create(self, meeting_id: int, seat_id: int, service_type: str, custom_text: str | None = None, attendee_id: int | None = None):
        if service_type not in self.VALID_SERVICE_TYPES:
            raise ValueError(f"service_type must be one of {sorted(self.VALID_SERVICE_TYPES)}")
        # Enforce: one pending call per seat
        existing = self.repo.get_pending_by_seat(meeting_id, seat_id)
        if existing:
            raise DuplicatePendingCallError(
                f"Seat {seat_id} already has a pending call in meeting {meeting_id}"
            )
        sc = self.repo.create(meeting_id, seat_id, service_type, custom_text, attendee_id=attendee_id)
        self.bus.publish(BaseEvent(
            name="service_call_created",
            payload={"call_id": sc.id, "seat_id": seat_id, "service_type": service_type},
        ))
        return sc

    def list_by_meeting(self, meeting_id: int):
        return self.repo.list_by_meeting(meeting_id)

    def get_pending_by_seat(self, meeting_id: int, seat_id: int):
        return self.repo.get_pending_by_seat(meeting_id, seat_id)

    def resolve(self, call_id: int):
        sc = self.repo.resolve(call_id)
        if not sc:
            raise ServiceCallNotFoundError(f"Service call {call_id} not found")
        self.bus.publish(BaseEvent(
            name="service_call_resolved",
            payload={"call_id": call_id},
        ))
        return sc

    def cancel(self, call_id: int, reason: str = "manual"):
        sc = self.repo.cancel(call_id, reason)
        if not sc:
            raise ServiceCallNotFoundError(f"Service call {call_id} not found")
        self.bus.publish(BaseEvent(
            name="service_call_cancelled",
            payload={"call_id": call_id, "reason": reason},
        ))
        return sc

    def cancel_expired(self, timeout_seconds: int = 300):
        expired = self.repo.cancel_expired(timeout_seconds)
        for sc in expired:
            self.bus.publish(BaseEvent(
                name="service_call_cancelled",
                payload={"call_id": sc.id, "reason": "TIMEOUT"},
            ))
        return expired
