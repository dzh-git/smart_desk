"""
ServiceCallService — service request lifecycle.

Per system_architecture §4.2, EVENT_BUS_SPEC §9:
    - All business rules enforced here.
    - Publishes service_call_created, service_call_resolved, service_call_cancelled events.
    - Uses ServiceCallRepository for data access.

Business rules:
    C1: pending → resolved.
    C2: pending → cancelled.
    C3: resolved 不可取消 (cannot cancel resolved).
    C4: cancelled 不可恢复 (cancelled cannot be restored — no restore method).
    Same seat: only 1 pending call at a time.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.events.event_bus import EventBus
from backend.events.service_call_events import (
    ServiceCallCreatedEvent,
    ServiceCallResolvedEvent,
    ServiceCallCancelledEvent,
)
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.models.service_call import ServiceCall
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.base import BaseService
from backend.services.meeting_service import MeetingService


class ServiceCallService(BaseService):
    """Service call lifecycle management.

    Business rules C1-C4 enforced here.
    Events published: service_call_created, service_call_resolved, service_call_cancelled.
    """

    def __init__(self, db: Session, event_bus: EventBus) -> None:
        super().__init__(db, event_bus)
        self.repo = ServiceCallRepository(db)
        self.meeting_service = MeetingService(db, event_bus)

    # ── Service Call CRUD ────────────────────────────────────────────────────

    def create_call(
        self, meeting_id: int, seat_id: int, service_type: str
    ) -> ServiceCall:
        """Create a new service call with status='pending'.

        Rule: same seat only 1 pending at a time.
        Publishes: service_call_created event.
        """
        self.meeting_service.require_editable_meeting(meeting_id)
        existing = self.repo.get_pending_by_seat(meeting_id, seat_id)
        if existing is not None:
            raise ConflictError(
                f"Seat {seat_id} already has a pending service call",
                "PENDING_CALL_EXISTS",
            )

        call = self.repo.create(
            meeting_id=meeting_id,
            seat_id=seat_id,
            service_type=service_type,
            status="pending",
        )

        self.event_bus.publish(
            ServiceCallCreatedEvent(
                meeting_id=meeting_id,
                payload={
                    "call_id": call.id,
                    "seat_id": seat_id,
                    "service_type": service_type,
                },
            )
        )

        return call

    def list_calls(self, meeting_id: int) -> list[ServiceCall]:
        """List all service calls for a meeting."""
        return self.repo.list_by_meeting(meeting_id)

    def get_current(self, meeting_id: int, seat_id: int) -> ServiceCall | None:
        """Return the pending call for a seat, or None."""
        return self.repo.get_pending_by_seat(meeting_id, seat_id)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _get_call(self, call_id: int) -> ServiceCall:
        """Get call by ID. Raises NotFoundError if missing."""
        call = self.repo.get_by_id(call_id)
        if not call:
            raise NotFoundError(
                f"Service call {call_id} not found",
                "SERVICE_CALL_NOT_FOUND",
            )
        return call

    def _assert_pending(self, call: ServiceCall) -> None:
        """Raise ValidationError if call is not pending."""
        self.meeting_service.require_editable_meeting(call.meeting_id)
        if call.status != "pending":
            raise ValidationError(
                f"Service call {call.id} is already {call.status}",
                "SERVICE_CALL_NOT_PENDING",
            )

    def resolve_call(self, call_id: int) -> ServiceCall:
        """Resolve a pending service call.

        C1: Only pending calls can be resolved.
        Publishes: service_call_resolved event.
        """
        call = self._get_call(call_id)
        self._assert_pending(call)

        call.status = "resolved"
        call.resolved_at = datetime.now(timezone.utc)
        self.repo.save(call)

        self.event_bus.publish(
            ServiceCallResolvedEvent(
                meeting_id=call.meeting_id,
                payload={"call_id": call_id, "seat_id": call.seat_id},
            )
        )

        return call

    def cancel_call(self, call_id: int) -> ServiceCall:
        """Cancel a pending service call.

        C2: Only pending calls can be cancelled.
        C3: Resolved calls cannot be cancelled (enforced by C2).
        C4: Cancelled calls cannot be restored (no restore method exists).
        Publishes: service_call_cancelled event.
        """
        call = self._get_call(call_id)
        self._assert_pending(call)

        call.status = "cancelled"
        self.repo.save(call)

        self.event_bus.publish(
            ServiceCallCancelledEvent(
                meeting_id=call.meeting_id,
                payload={"call_id": call_id, "seat_id": call.seat_id},
            )
        )

        return call
