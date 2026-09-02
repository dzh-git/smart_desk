"""Stable person identity shared across meetings."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String

from backend.database import Base


class Person(Base):
    __tablename__ = "people"

    # Stable external identifier returned by the on-device face recognizer.
    id = Column(String(64), primary_key=True)
    name = Column(String(100), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
