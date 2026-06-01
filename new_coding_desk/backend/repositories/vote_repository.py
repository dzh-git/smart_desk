"""
VoteRepository — CRUD for votes + vote_records.

Per DATABASE_SCHEMA.md §8-9, §15:
    Owns: votes, vote_records
    No business logic.
"""
from __future__ import annotations

from backend.models.vote import Vote
from backend.models.vote_record import VoteRecord
from backend.repositories.base import BaseRepository


class VoteRepository(BaseRepository[Vote]):
    """Data access for votes and vote_records.

    Extends BaseRepository[Vote] with:
        - Open vote lookup
        - VoteRecord CRUD
    """

    model = Vote

    # ── Vote queries ─────────────────────────────────────────────────────────

    def get_open_vote(self) -> Vote | None:
        """Return the vote with status='open', or None."""
        return self.db.query(Vote).filter(Vote.status == "open").first()

    # ── VoteRecord CRUD ──────────────────────────────────────────────────────

    def get_record(self, vote_id: int, attendee_id: int) -> VoteRecord | None:
        """Get a vote record by vote_id and attendee_id."""
        return (
            self.db.query(VoteRecord)
            .filter(
                VoteRecord.vote_id == vote_id,
                VoteRecord.attendee_id == attendee_id,
            )
            .first()
        )

    def create_record(self, **kwargs) -> VoteRecord:
        """Create a vote record. Auto-commits."""
        record = VoteRecord(**kwargs)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def save_record(self, record: VoteRecord) -> VoteRecord:
        """Persist changes to an existing vote record."""
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_records_by_vote(self, vote_id: int) -> list[VoteRecord]:
        """List all records for a vote."""
        return (
            self.db.query(VoteRecord)
            .filter(VoteRecord.vote_id == vote_id)
            .all()
        )

    def count_records_by_vote(self, vote_id: int) -> int:
        """Count records for a vote."""
        return (
            self.db.query(VoteRecord)
            .filter(VoteRecord.vote_id == vote_id)
            .count()
        )
