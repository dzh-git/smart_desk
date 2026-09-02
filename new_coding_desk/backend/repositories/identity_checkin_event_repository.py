"""Persistence helpers for identity check-in idempotency."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.models.identity_checkin_event import IdentityCheckInEvent


class IdentityCheckInEventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, event_id: str) -> IdentityCheckInEvent | None:
        return self.db.get(IdentityCheckInEvent, event_id)

    def save(
        self,
        event: IdentityCheckInEvent,
        *,
        commit: bool = True,
    ) -> IdentityCheckInEvent:
        self.db.add(event)
        if commit:
            self.db.commit()
            self.db.refresh(event)
        else:
            self.db.flush()
        return event
