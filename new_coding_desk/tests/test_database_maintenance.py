from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import Base
from backend.database_maintenance import apply_schema_with_backup
from backend.migrations import (
    ensure_agenda_columns,
    ensure_attendee_identity_columns,
    ensure_tablet_device_status_columns,
    ensure_translation_record_columns,
)
from backend.models.person import Person
from backend.models.tablet_device import TabletDevice


def test_schema_failure_restores_original_database(tmp_path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO sample (id) VALUES (1)")
        connection.commit()
    finally:
        connection.close()
    engine = create_engine(f"sqlite:///{database_path}")

    def failing_upgrade() -> None:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE sample ADD COLUMN transient TEXT")
            )
        raise RuntimeError("injected migration failure")

    with pytest.raises(RuntimeError, match="injected migration failure"):
        apply_schema_with_backup(
            engine,
            failing_upgrade,
            backup_dir=tmp_path / "backups",
            skip_test_database=False,
        )

    restored = create_engine(f"sqlite:///{database_path}")
    with restored.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(sample)"))
        }
        count = connection.execute(
            text("SELECT COUNT(*) FROM sample")
        ).scalar_one()
    assert columns == {"id"}
    assert count == 1
    assert len(list((tmp_path / "backups").glob("*.db"))) == 1


def test_successful_schema_upgrade_is_repeatable(tmp_path):
    database_path = tmp_path / "repeatable.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO sample (id) VALUES (1)")
        connection.commit()
    finally:
        connection.close()
    engine = create_engine(f"sqlite:///{database_path}")

    def upgrade() -> None:
        with engine.begin() as connection:
            existing = {
                row[1]
                for row in connection.execute(
                    text("PRAGMA table_info(sample)")
                )
            }
            if "label" not in existing:
                connection.execute(
                    text("ALTER TABLE sample ADD COLUMN label TEXT")
                )

    first = apply_schema_with_backup(
        engine,
        upgrade,
        backup_dir=tmp_path / "backups",
        skip_test_database=False,
    )
    second = apply_schema_with_backup(
        engine,
        upgrade,
        backup_dir=tmp_path / "backups",
        skip_test_database=False,
    )

    assert first is not None
    assert second is not None
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM sample")
        ).scalar_one() == 1


def test_real_schema_migrations_preserve_data_and_constraints(tmp_path):
    """Run the production migration set twice on an isolated DB copy."""
    database_path = tmp_path / "production-copy.db"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Person(id="person-preserved", name="Preserved Person"))
        session.add(
            TabletDevice(
                id="tablet-seat-01",
                seat_id=1,
                token_hash="fixture-hash",
                enabled=True,
            )
        )
        session.commit()

    def production_upgrade() -> None:
        Base.metadata.create_all(engine)
        ensure_translation_record_columns(engine)
        ensure_agenda_columns(engine)
        ensure_attendee_identity_columns(engine)
        ensure_tablet_device_status_columns(engine)

    first_backup = apply_schema_with_backup(
        engine,
        production_upgrade,
        backup_dir=tmp_path / "backups",
        skip_test_database=False,
    )
    second_backup = apply_schema_with_backup(
        engine,
        production_upgrade,
        backup_dir=tmp_path / "backups",
        skip_test_database=False,
    )

    with Session(engine) as session:
        assert session.query(Person).count() == 1
        assert session.query(TabletDevice).count() == 1
        session.add(
            TabletDevice(
                id="duplicate-seat",
                seat_id=1,
                token_hash="fixture-hash-2",
                enabled=True,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    assert first_backup is not None and first_backup.is_file()
    assert second_backup is not None and second_backup.is_file()
