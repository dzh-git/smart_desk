"""
SeatRepository — CRUD for seat_states + speaker_seat.

Per DATABASE_SCHEMA.md §6-7, §15:
    Owns: seat_states, speaker_seat
    No business logic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.models.seat_state import SeatState
from backend.models.speaker_seat import SpeakerSeat

logger = logging.getLogger(__name__)

SEAT_COUNT = 10


class SeatRepository:
    """Data access for seat_states and speaker_seat.

    Does NOT extend BaseRepository — seats use seat_id as PK (non-auto-increment),
    and speaker_seat is a singleton row.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Seed ─────────────────────────────────────────────────────────────────

    @staticmethod
    def init_seats(db: Session) -> None:
        """Seed initial seat_states (1..10, vacant) and speaker_seat (id=1, NULL).

        Idempotent: skips if data already exists.
        Called once at application startup.
        """
        existing = db.query(SeatState).count()
        if existing == 0:
            now = datetime.now(timezone.utc)
            for seat_id in range(1, SEAT_COUNT + 1):
                db.add(SeatState(seat_id=seat_id, status="vacant", updated_at=now))
            db.commit()
            logger.info("SeatRepository: seeded %d seat_states", SEAT_COUNT)

        speaker = db.get(SpeakerSeat, 1)
        if speaker is None:
            db.add(SpeakerSeat(id=1, seat_id=None))
            db.commit()
            logger.info("SeatRepository: seeded speaker_seat")

    # ── SeatState ────────────────────────────────────────────────────────────

    def get_seat(self, seat_id: int) -> SeatState | None:
        """Get a seat by its seat_id (1..10)."""
        return self.db.get(SeatState, seat_id)

    def list_seats(self) -> list[SeatState]:
        """List all 10 seats, ordered by seat_id."""
        return (
            self.db.query(SeatState)
            .order_by(SeatState.seat_id)
            .all()
        )

    def save_seat(self, seat: SeatState) -> SeatState:
        """Persist changes to a seat."""
        seat.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(seat)
        return seat

    # ── SpeakerSeat ──────────────────────────────────────────────────────────

    def get_speaker_seat(self) -> SpeakerSeat:
        """Return the singleton speaker_seat row (id=1).

        Raises RuntimeError if not seeded.
        """
        speaker = self.db.get(SpeakerSeat, 1)
        if speaker is None:
            raise RuntimeError("speaker_seat not initialized — call init_seats() first")
        return speaker

    def save_speaker_seat(self, speaker: SpeakerSeat) -> SpeakerSeat:
        """Persist changes to the speaker_seat row."""
        speaker.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(speaker)
        return speaker
