"""
Migrations — idempotent schema updates for SQLite.

Phase 4:
    Add utterance_id and source_type columns to translation_records.
    Uses PRAGMA table_info to check column existence before ALTER TABLE,
    so repeated startup never fails and never drops data.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)

# ── Column definitions ───────────────────────────────────────────────────────

_COLUMNS_TO_ADD: dict[str, str] = {
    "utterance_id": "VARCHAR(64)",
    "source_type": "VARCHAR(32) DEFAULT 'speech_ws'",
}


def ensure_translation_record_columns(engine) -> None:
    """Idempotently add Phase 4 columns to translation_records.

    Checks existing columns via SQLAlchemy inspector.
    Only ALTER TABLE if the column is missing.
    Safe to call on every startup.
    """
    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("translation_records")}

    with engine.connect() as conn:
        for col_name, col_type in _COLUMNS_TO_ADD.items():
            if col_name in existing:
                logger.debug("Column %s already exists — skipping", col_name)
                continue
            stmt = f"ALTER TABLE translation_records ADD COLUMN {col_name} {col_type}"
            conn.execute(text(stmt))
            logger.info("Added column %s to translation_records", col_name)
        conn.commit()


# ── Phase 1: Agenda state machine columns ───────────────────────────────────

_AGENDA_COLUMNS_TO_ADD: dict[str, str] = {
    "status": "VARCHAR(20) DEFAULT 'pending' NOT NULL",
    "started_at": "DATETIME",
    "completed_at": "DATETIME",
    "skipped_at": "DATETIME",
}


def ensure_agenda_columns(engine) -> None:
    """Idempotently add Phase 1 columns to agendas.

    Checks existing columns via SQLAlchemy inspector.
    Only ALTER TABLE if the column is missing.
    Safe to call on every startup.
    """
    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("agendas")}

    with engine.connect() as conn:
        for col_name, col_type in _AGENDA_COLUMNS_TO_ADD.items():
            if col_name in existing:
                logger.debug("Column %s already exists in agendas — skipping", col_name)
                continue
            stmt = f"ALTER TABLE agendas ADD COLUMN {col_name} {col_type}"
            conn.execute(text(stmt))
            logger.info("Added column %s to agendas", col_name)
        conn.commit()


# ── Android tablet identity integration ─────────────────────────────────────

_ATTENDEE_IDENTITY_COLUMNS_TO_ADD: dict[str, str] = {
    "person_id": "VARCHAR(64)",
    "assigned_seat_id": "INTEGER",
}


def ensure_attendee_identity_columns(engine) -> None:
    """Add the stable Person link to existing attendee tables.

    Fresh databases receive the full foreign key and unique constraint from
    SQLAlchemy metadata. Existing SQLite databases cannot add those constraints
    with ALTER COLUMN, so a partial unique index enforces one Person per meeting
    while preserving legacy rows whose person_id is NULL.
    """
    inspector = inspect(engine)
    if "attendees" not in inspector.get_table_names():
        return
    existing = {
        column["name"]
        for column in inspector.get_columns("attendees")
    }

    with engine.connect() as conn:
        for column_name, column_type in (
            _ATTENDEE_IDENTITY_COLUMNS_TO_ADD.items()
        ):
            if column_name in existing:
                continue
            conn.execute(
                text(
                    "ALTER TABLE attendees "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )
            logger.info("Added column %s to attendees", column_name)

        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_attendees_person_id "
                "ON attendees(person_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_attendees_assigned_seat_id "
                "ON attendees(assigned_seat_id)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_attendees_meeting_person_id "
                "ON attendees(meeting_id, person_id) "
                "WHERE person_id IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_attendees_meeting_assigned_seat_id "
                "ON attendees(meeting_id, assigned_seat_id) "
                "WHERE assigned_seat_id IS NOT NULL"
            )
        )
        conn.commit()


_TABLET_STATUS_COLUMNS_TO_ADD: dict[str, str] = {
    "camera_status": "VARCHAR(32)",
    "face_model_status": "VARCHAR(32)",
    "registered_templates_count": "INTEGER",
    "microphone_status": "VARCHAR(32)",
    "meeting_websocket_status": "VARCHAR(32)",
    "diagnostic_status": "VARCHAR(32)",
    "face_transport_public_key": "TEXT",
    "face_transport_key_fingerprint": "VARCHAR(64)",
    "face_template_sync_status": "VARCHAR(32)",
    "face_template_set_revision": "INTEGER",
    "face_template_meeting_id": "INTEGER",
    "face_template_sync_count": "INTEGER",
    "face_template_sync_error": "VARCHAR(300)",
}


def ensure_tablet_device_status_columns(engine) -> None:
    """Idempotently upgrade existing tablet device registries."""
    inspector = inspect(engine)
    if "tablet_devices" not in inspector.get_table_names():
        return
    existing = {
        column["name"]
        for column in inspector.get_columns("tablet_devices")
    }
    with engine.connect() as conn:
        for column_name, column_type in (
            _TABLET_STATUS_COLUMNS_TO_ADD.items()
        ):
            if column_name in existing:
                continue
            conn.execute(
                text(
                    "ALTER TABLE tablet_devices "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )
            logger.info(
                "Added column %s to tablet_devices",
                column_name,
            )
        conn.commit()


def ensure_face_template_meeting_columns(engine) -> None:
    """Add the meeting template-set revision to upgraded databases."""
    inspector = inspect(engine)
    if "meetings" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("meetings")}
    if "face_template_set_revision" in existing:
        return
    with engine.connect() as conn:
        conn.execute(
            text(
                "ALTER TABLE meetings ADD COLUMN "
                "face_template_set_revision INTEGER DEFAULT 0 NOT NULL"
            )
        )
        conn.commit()
