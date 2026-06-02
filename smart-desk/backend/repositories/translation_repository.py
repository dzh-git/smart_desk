from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from backend.models import TranslationRecord


class TranslationRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, meeting_id: int, seat_id: int,
               source_lang: str, target_lang: str,
               source_text: str, translated_text: str) -> TranslationRecord:
        stmt = sqlite_insert(TranslationRecord).values(
            meeting_id=meeting_id,
            seat_id=seat_id,
            source_lang=source_lang,
            target_lang=target_lang,
            source_text=source_text,
            translated_text=translated_text,
        ).on_conflict_do_update(
            index_elements=[
                'meeting_id', 'seat_id', 'source_lang', 'target_lang', 'source_text',
            ],
            set_=dict(translated_text=translated_text),
        )
        self.db.execute(stmt)
        self.db.commit()
        return self.db.query(TranslationRecord).filter(
            TranslationRecord.meeting_id == meeting_id,
            TranslationRecord.seat_id == seat_id,
            TranslationRecord.source_lang == source_lang,
            TranslationRecord.target_lang == target_lang,
            TranslationRecord.source_text == source_text,
        ).first()

    def list_by_meeting(self, meeting_id: int, limit: int = 500) -> list[TranslationRecord]:
        return self.db.query(TranslationRecord).filter(
            TranslationRecord.meeting_id == meeting_id
        ).order_by(TranslationRecord.created_at.desc()).limit(limit).all()

    def list_by_meeting_seat(self, meeting_id: int, seat_id: int, limit: int = 50) -> list[TranslationRecord]:
        return self.db.query(TranslationRecord).filter(
            TranslationRecord.meeting_id == meeting_id,
            TranslationRecord.seat_id == seat_id,
        ).order_by(TranslationRecord.created_at.desc()).limit(limit).all()

    def delete_by_meeting(self, meeting_id: int) -> int:
        count = self.db.query(TranslationRecord).filter(
            TranslationRecord.meeting_id == meeting_id
        ).delete()
        self.db.commit()
        return count

    def cleanup_expired(self, retention_days: int = 180) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        count = self.db.query(TranslationRecord).filter(
            TranslationRecord.created_at < cutoff
        ).delete()
        self.db.commit()
        return count
