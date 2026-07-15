"""
TranslationRepository — CRUD for translation_records.

Per DATABASE_SCHEMA.md §11, §15:
    Owns: translation_records
    No business logic.
"""
from __future__ import annotations

import re

from backend.models.translation_record import TranslationRecord
from backend.repositories.base import BaseRepository


class TranslationRepository(BaseRepository[TranslationRecord]):
    """Data access for translation_records.

    Extends BaseRepository[TranslationRecord] with:
        - Meeting-scoped listing with optional seat filter
    """

    model = TranslationRecord

    # ── Custom queries ───────────────────────────────────────────────────────

    def list_by_meeting(
        self, meeting_id: int, seat_id: int | None = None
    ) -> list[TranslationRecord]:
        """List translation records for a meeting, newest first.

        Args:
            meeting_id: Required meeting filter.
            seat_id: Optional seat filter. If None, returns all seats.
        """
        q = (
            self.db.query(TranslationRecord)
            .filter(TranslationRecord.meeting_id == meeting_id)
        )
        if seat_id is not None:
            q = q.filter(TranslationRecord.seat_id == seat_id)
        return q.order_by(TranslationRecord.created_at.desc()).all()

    def max_utterance_sequence(self, meeting_id: int, seat_id: int) -> int:
        """Return the largest persisted speech utterance sequence."""
        prefix = f"utt_{meeting_id}_{seat_id}_"
        values = (
            self.db.query(TranslationRecord.utterance_id)
            .filter(
                TranslationRecord.meeting_id == meeting_id,
                TranslationRecord.seat_id == seat_id,
                TranslationRecord.utterance_id.like(f"{prefix}%"),
            )
            .all()
        )
        pattern = re.compile(rf"^{re.escape(prefix)}(\d{{6}})$")
        sequences = [
            int(match.group(1))
            for (value,) in values
            if value and (match := pattern.match(value))
        ]
        return max(sequences, default=0)
