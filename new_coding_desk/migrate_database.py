"""Apply the production schema with backup/rollback and print safe evidence."""
from __future__ import annotations

import json

from backend.database import DB_PATH, engine
from backend.database_maintenance import (
    apply_schema_with_backup,
    verify_database_integrity,
)
from backend.schema import upgrade_database_schema


def main() -> None:
    backup = apply_schema_with_backup(
        engine,
        lambda: upgrade_database_schema(engine),
    )
    verify_database_integrity(engine)
    print(
        json.dumps(
            {
                "status": "PASS",
                "database": DB_PATH.name,
                "backupCreated": backup is not None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
