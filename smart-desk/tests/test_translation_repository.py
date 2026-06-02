import pytest
from backend.repositories.translation_repository import TranslationRepository


def test_upsert_translation(db_session):
    db, meeting_id = db_session
    repo = TranslationRepository(db)
    t = repo.upsert(meeting_id=meeting_id, seat_id=3,
                    source_lang="zh", target_lang="en",
                    source_text="你好", translated_text="Hello")
    assert t.id is not None
    assert t.source_text == "你好"
    assert t.translated_text == "Hello"


def test_upsert_updates_existing(db_session):
    db, meeting_id = db_session
    repo = TranslationRepository(db)
    t1 = repo.upsert(meeting_id=meeting_id, seat_id=3,
                     source_lang="zh", target_lang="en",
                     source_text="你好", translated_text="Hello")
    t2 = repo.upsert(meeting_id=meeting_id, seat_id=3,
                     source_lang="zh", target_lang="en",
                     source_text="你好", translated_text="Hi")
    assert t1.id == t2.id
    assert t2.translated_text == "Hi"
    # Verify only one record exists (no duplicate)
    records = repo.list_by_meeting(meeting_id)
    matching = [r for r in records
                if r.seat_id == 3 and r.source_text == "你好"]
    assert len(matching) == 1


def test_cleanup_expired(db_session):
    db, meeting_id = db_session
    repo = TranslationRepository(db)
    t = repo.upsert(meeting_id=meeting_id, seat_id=1,
                    source_lang="zh", target_lang="en",
                    source_text="test", translated_text="test")
    # Force old date
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text
    old = datetime.now(timezone.utc) - timedelta(days=200)
    db.execute(text("UPDATE translation_records SET created_at = :dt WHERE id = :id"),
               {"dt": old, "id": t.id})
    db.commit()
    count = repo.cleanup_expired(180)
    assert count >= 1


def test_list_by_meeting_seat(db_session):
    db, meeting_id = db_session
    repo = TranslationRepository(db)
    repo.upsert(meeting_id=meeting_id, seat_id=1,
                source_lang="zh", target_lang="en",
                source_text="你好", translated_text="Hello")
    repo.upsert(meeting_id=meeting_id, seat_id=1,
                source_lang="zh", target_lang="en",
                source_text="谢谢", translated_text="Thanks")
    repo.upsert(meeting_id=meeting_id, seat_id=2,
                source_lang="zh", target_lang="en",
                source_text="再见", translated_text="Goodbye")
    seat1 = repo.list_by_meeting_seat(meeting_id, seat_id=1, limit=50)
    assert len(seat1) == 2
    seat2 = repo.list_by_meeting_seat(meeting_id, seat_id=2, limit=50)
    assert len(seat2) == 1
    assert seat2[0].source_text == "再见"


def test_delete_by_meeting(db_session):
    db, meeting_id = db_session
    repo = TranslationRepository(db)
    repo.upsert(meeting_id=meeting_id, seat_id=1,
                source_lang="zh", target_lang="en",
                source_text="你好", translated_text="Hello")
    repo.upsert(meeting_id=meeting_id, seat_id=1,
                source_lang="zh", target_lang="en",
                source_text="谢谢", translated_text="Thanks")
    count = repo.delete_by_meeting(meeting_id)
    assert count == 2
    remaining = repo.list_by_meeting(meeting_id)
    assert len(remaining) == 0


def test_cleanup_expired_no_expired(db_session):
    db, meeting_id = db_session
    repo = TranslationRepository(db)
    repo.upsert(meeting_id=meeting_id, seat_id=1,
                source_lang="zh", target_lang="en",
                source_text="test", translated_text="test")
    count = repo.cleanup_expired(180)
    assert count == 0


def test_upsert_empty_strings(db_session):
    db, meeting_id = db_session
    repo = TranslationRepository(db)
    t = repo.upsert(meeting_id=meeting_id, seat_id=2,
                    source_lang="en", target_lang="zh",
                    source_text="", translated_text="")
    assert t.id is not None
    assert t.source_text == ""
    assert t.translated_text == ""
