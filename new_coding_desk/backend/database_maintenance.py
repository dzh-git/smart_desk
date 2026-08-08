"""SQLite startup backup, integrity checking, and rollback helpers."""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine


SchemaUpgrade = Callable[[], None]


def sqlite_database_path(engine: Engine) -> Path | None:
    """Return the on-disk SQLite path, or None for non-file databases."""
    if engine.url.get_backend_name() != "sqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database).resolve()


def create_database_backup(
    database_path: Path,
    backup_dir: Path,
) -> Path:
    """Create a consistent SQLite backup without copying a live WAL blindly."""
    database_path = database_path.resolve()
    backup_dir = backup_dir.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"smart_desk-{timestamp}.db"
    suffix = 1
    while backup_path.exists():
        backup_path = backup_dir / f"smart_desk-{timestamp}-{suffix}.db"
        suffix += 1

    with closing(sqlite3.connect(database_path)) as source:
        with closing(sqlite3.connect(backup_path)) as destination:
            source.backup(destination)
    return backup_path


def restore_database_backup(
    backup_path: Path,
    database_path: Path,
) -> None:
    """Restore one verified backup over the failed working database."""
    backup_path = backup_path.resolve()
    database_path = database_path.resolve()
    if not backup_path.is_file():
        raise FileNotFoundError(backup_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    restore_temp = database_path.with_suffix(database_path.suffix + ".restore")
    shutil.copy2(backup_path, restore_temp)
    restore_temp.replace(database_path)


def verify_database_integrity(engine: Engine) -> None:
    """Fail when SQLite does not report a clean database."""
    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.connect() as connection:
        result = connection.execute(text("PRAGMA integrity_check")).scalar()
    if result != "ok":
        raise RuntimeError(f"SQLite integrity_check failed: {result}")


def apply_schema_with_backup(
    engine: Engine,
    upgrade: SchemaUpgrade,
    *,
    backup_dir: Path | None = None,
    skip_test_database: bool = True,
) -> Path | None:
    """Back up an existing SQLite DB, apply schema, and restore on failure."""
    database_path = sqlite_database_path(engine)
    backup_path: Path | None = None
    is_test_database = (
        database_path is not None
        and database_path.name.endswith(".test.db")
    )
    should_backup = (
        database_path is not None
        and database_path.exists()
        and database_path.stat().st_size > 0
        and not (skip_test_database and is_test_database)
    )
    if should_backup:
        destination = backup_dir or database_path.parent / "backups"
        backup_path = create_database_backup(database_path, destination)

    try:
        upgrade()
        verify_database_integrity(engine)
    except Exception:
        if backup_path is not None and database_path is not None:
            engine.dispose()
            restore_database_backup(backup_path, database_path)
        raise
    return backup_path


__all__ = [
    "apply_schema_with_backup",
    "create_database_backup",
    "restore_database_backup",
    "sqlite_database_path",
    "verify_database_integrity",
]
