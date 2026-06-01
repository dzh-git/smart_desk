"""
TranslationRepository — CRUD for translation_records.

Per DATABASE_SCHEMA.md §11, §15:
    Owns: translation_records
    No business logic.
"""
from __future__ import annotations

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
