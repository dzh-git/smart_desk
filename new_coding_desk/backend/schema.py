"""Single production schema-upgrade entry used by startup and installers."""
from __future__ import annotations

from sqlalchemy.engine import Engine

from backend import models as _models  # noqa: F401 - registers all Base tables
from backend.database import Base
from backend.migrations import (
    ensure_agenda_columns,
    ensure_attendee_identity_columns,
    ensure_tablet_device_status_columns,
    ensure_translation_record_columns,
    ensure_face_template_meeting_columns,
)


def upgrade_database_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_translation_record_columns(engine)
    ensure_agenda_columns(engine)
    ensure_attendee_identity_columns(engine)
    ensure_tablet_device_status_columns(engine)
    ensure_face_template_meeting_columns(engine)


__all__ = ["upgrade_database_schema"]
