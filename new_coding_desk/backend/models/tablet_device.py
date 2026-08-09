"""Trusted Android tablet binding and operational status."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from backend.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TabletDevice(Base):
    __tablename__ = "tablet_devices"

    id = Column(String(64), primary_key=True)
    seat_id = Column(Integer, nullable=False, unique=True, index=True)
    token_hash = Column(String(256), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    app_version = Column(String(64), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    camera_status = Column(String(32), nullable=True)
    face_model_status = Column(String(32), nullable=True)
    registered_templates_count = Column(Integer, nullable=True)
    microphone_status = Column(String(32), nullable=True)
    meeting_websocket_status = Column(String(32), nullable=True)
    diagnostic_status = Column(String(32), nullable=True)
    last_error = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    @property
    def seat_alias(self) -> str:
        return f"tablet-seat-{self.seat_id:02d}"
