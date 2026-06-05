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
