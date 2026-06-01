"""
BaseService — common dependency injection for all services.

Subclass and declare required repositories in __init__.

Usage:
    class MeetingService(BaseService):
        def __init__(self, db: Session, event_bus: EventBus):
            super().__init__(db, event_bus)
            self.meeting_repo = MeetingRepository(db)
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.events.event_bus import EventBus


class BaseService:
    """Base class for all service-layer classes.

    Provides:
        self.db        — SQLAlchemy session
        self.event_bus — process-internal EventBus singleton
    """

    def __init__(self, db: Session, event_bus: EventBus) -> None:
        self.db = db
        self.event_bus = event_bus
