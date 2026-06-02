"""HistoryStore — SQLite-backed translation history persistence.

Provides CRUD operations for storing and querying speech recognition
results. Thread-safe via SQLite's built-in serialized mode.

Usage:
    store = HistoryStore("history.db")
    store.insert(meeting_id=1, seat_id=3, segment_id=1,
                 zh_text="你好世界", en_text="Hello world")
    rows = store.query_by_meeting(meeting_id=1)
    store.close()
"""

from __future__ import annotations
import sqlite3
import os
import threading
from datetime import datetime


class HistoryStore:
    """SQLite-backed store for translation history records.

    Each record: (meeting_id, seat_id, segment_id, zh_text, en_text, timestamp).
    Unique constraint on (meeting_id, seat_id, segment_id) — use upsert()
    to update an existing segment.
    """

    def __init__(self, db_path: str = ":memory:"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self):
        """Create tables and indexes if not exist."""
        conn = self._get_conn()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS translation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id INTEGER NOT NULL,
                seat_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                zh_text TEXT NOT NULL DEFAULT '',
                en_text TEXT NOT NULL DEFAULT '',
                is_final INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(meeting_id, seat_id, segment_id)
            );

            CREATE INDEX IF NOT EXISTS idx_meeting_seat
                ON translation_history(meeting_id, seat_id);

            CREATE INDEX IF NOT EXISTS idx_created_at
                ON translation_history(meeting_id, created_at);
        """)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Lazy-connect with thread safety."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    # ── Write Operations ──────────────────────────────────────────────────

    def insert(
        self,
        meeting_id: int,
        seat_id: int,
        segment_id: int,
        zh_text: str,
        en_text: str = "",
        is_final: bool = True,
    ) -> int:
        """Insert a new history record. Returns row id.

        Raises sqlite3.IntegrityError if (meeting_id, seat_id, segment_id)
        already exists. Use upsert() to tolerate duplicates.
        """
        with self._lock:
            cur = self._get_conn().execute(
                """INSERT INTO translation_history
                   (meeting_id, seat_id, segment_id, zh_text, en_text, is_final)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (meeting_id, seat_id, segment_id, zh_text, en_text,
                 1 if is_final else 0),
            )
            self._get_conn().commit()
            return cur.lastrowid

    def upsert(
        self,
        meeting_id: int,
        seat_id: int,
        segment_id: int,
        zh_text: str,
        en_text: str = "",
        is_final: bool = True,
    ) -> int:
        """Insert or replace a history record. Returns row id."""
        with self._lock:
            cur = self._get_conn().execute(
                """INSERT OR REPLACE INTO translation_history
                   (meeting_id, seat_id, segment_id, zh_text, en_text, is_final,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?,
                           COALESCE((SELECT created_at FROM translation_history
                                     WHERE meeting_id=? AND seat_id=? AND segment_id=?),
                                    datetime('now', 'localtime')))""",
                (meeting_id, seat_id, segment_id, zh_text, en_text,
                 1 if is_final else 0,
                 meeting_id, seat_id, segment_id),
            )
            self._get_conn().commit()
            return cur.lastrowid

    # ── Query Operations ──────────────────────────────────────────────────

    def query_by_meeting(
        self, meeting_id: int,
        limit: int = 200, offset: int = 0,
    ) -> list[dict]:
        """Return all history records for a meeting, ordered by time."""
        rows = self._get_conn().execute(
            """SELECT id, meeting_id, seat_id, segment_id, zh_text, en_text,
                      is_final, created_at
               FROM translation_history
               WHERE meeting_id = ?
               ORDER BY created_at ASC, segment_id ASC
               LIMIT ? OFFSET ?""",
            (meeting_id, limit, offset),
        ).fetchall()

        return [_row_to_dict(r) for r in rows]

    def query_by_seat(
        self, meeting_id: int, seat_id: int,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        """Return history records for a specific seat in a meeting."""
        rows = self._get_conn().execute(
            """SELECT id, meeting_id, seat_id, segment_id, zh_text, en_text,
                      is_final, created_at
               FROM translation_history
               WHERE meeting_id = ? AND seat_id = ?
               ORDER BY created_at ASC, segment_id ASC
               LIMIT ? OFFSET ?""",
            (meeting_id, seat_id, limit, offset),
        ).fetchall()

        return [_row_to_dict(r) for r in rows]

    def get_last_segment_id(
        self, meeting_id: int, seat_id: int,
    ) -> int:
        """Return the largest segment_id for a meeting-seat pair.

        Returns 0 if no records exist (next segment_id should be 1).
        """
        row = self._get_conn().execute(
            """SELECT MAX(segment_id) FROM translation_history
               WHERE meeting_id = ? AND seat_id = ?""",
            (meeting_id, seat_id),
        ).fetchone()
        return row[0] if row[0] is not None else 0

    def get_segment_count(
        self, meeting_id: int, seat_id: int | None = None,
    ) -> int:
        """Count segments in a meeting, optionally filtered by seat."""
        if seat_id is not None:
            row = self._get_conn().execute(
                "SELECT COUNT(*) FROM translation_history WHERE meeting_id=? AND seat_id=?",
                (meeting_id, seat_id),
            ).fetchone()
        else:
            row = self._get_conn().execute(
                "SELECT COUNT(*) FROM translation_history WHERE meeting_id=?",
                (meeting_id,),
            ).fetchone()
        return row[0] if row else 0

    # ── Maintenance ───────────────────────────────────────────────────────

    def cleanup_old(self, days: int = 30) -> int:
        """Delete records older than N days. Returns count of deleted rows."""
        with self._lock:
            cur = self._get_conn().execute(
                """DELETE FROM translation_history
                   WHERE created_at < datetime('now', 'localtime', ?)""",
                (f"-{days} days",),
            )
            self._get_conn().commit()
            return cur.rowcount

    def close(self):
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _row_to_dict(row: tuple) -> dict:
    """Convert a DB row tuple to a dict."""
    return {
        "id": row[0],
        "meeting_id": row[1],
        "seat_id": row[2],
        "segment_id": row[3],
        "zh_text": row[4],
        "en_text": row[5],
        "is_final": bool(row[6]),
        "created_at": row[7],
    }
