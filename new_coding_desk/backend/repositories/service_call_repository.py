"""
ServiceCallRepository — CRUD for service_calls.

Per DATABASE_SCHEMA.md §10, §15:
    Owns: service_calls
    No business logic.
"""
from __future__ import annotations

from backend.models.service_call import ServiceCall
from backend.repositories.base import BaseRepository


class ServiceCallRepository(BaseRepository[ServiceCall]):
    """Data access for service_calls.

    Extends BaseRepository[ServiceCall] with:
        - Pending-by-seat lookup
        - Meeting-scoped listings
    """

    model = ServiceCall

    # ── Custom queries ───────────────────────────────────────────────────────

    def get_pending_by_seat(
        self, meeting_id: int, seat_id: int
    ) -> ServiceCall | None:
        """Return the pending call for a seat in a meeting, or None."""
        return (
            self.db.query(ServiceCall)
            .filter(
                ServiceCall.meeting_id == meeting_id,
                ServiceCall.seat_id == seat_id,
                ServiceCall.status == "pending",
            )
            .first()
        )

    def list_by_meeting(self, meeting_id: int) -> list[ServiceCall]:
        """List all service calls for a meeting, newest first."""
        return (
            self.db.query(ServiceCall)
            .filter(ServiceCall.meeting_id == meeting_id)
            .order_by(ServiceCall.created_at.desc())
            .all()
        )

    def list_pending(self, meeting_id: int) -> list[ServiceCall]:
        """List all pending service calls for a meeting."""
        return (
            self.db.query(ServiceCall)
            .filter(
                ServiceCall.meeting_id == meeting_id,
                ServiceCall.status == "pending",
            )
            .order_by(ServiceCall.created_at.asc())
            .all()
        )
