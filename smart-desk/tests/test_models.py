import pytest


def test_translation_record_columns():
    """Verify TranslationRecord has the required columns."""
    from backend.models import TranslationRecord
    cols = {c.name for c in TranslationRecord.__table__.columns}
    assert "id" in cols
    assert "meeting_id" in cols
    assert "seat_id" in cols
    assert "source_lang" in cols
    assert "target_lang" in cols
    assert "source_text" in cols
    assert "translated_text" in cols
    assert "created_at" in cols


def test_seat_state_columns():
    from backend.models import SeatState
    cols = {c.name for c in SeatState.__table__.columns}
    assert "seat_id" in cols
    assert "status" in cols
    assert "attendee_id" in cols
    assert "updated_at" in cols


def test_seat_state_defaults():
    from backend.models import SeatState
    s = SeatState(seat_id=1)
    assert s.status == "vacant"
    assert s.attendee_id is None


def test_speaker_seat_columns():
    from backend.models import SpeakerSeat
    cols = {c.name for c in SpeakerSeat.__table__.columns}
    assert "id" in cols
    assert "seat_id" in cols
    assert "updated_at" in cols


def test_speaker_seat_defaults():
    from backend.models import SpeakerSeat
    s = SpeakerSeat(id=1)
    assert s.seat_id is None


def test_meeting_has_translation_records_relationship():
    from backend.models import Meeting
    rels = {r.key for r in Meeting.__mapper__.relationships}
    assert "translation_records" in rels


def test_models_create_all_tables():
    """Verify all 9 tables (including new ones) exist after create_all.
    Uses in-memory SQLite to avoid modifying production database."""
    from backend.database import Base
    import backend.models  # noqa: F401  ensure all ORM models are registered on Base.metadata
    from sqlalchemy import create_engine, inspect
    mem_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=mem_engine)
    inspector = inspect(mem_engine)
    tables = inspector.get_table_names()
    expected_tables = [
        "meetings", "agendas", "attendees",
        "votes", "vote_records", "service_calls",
        "translation_records", "seat_states", "speaker_seat",
    ]
    assert len(tables) == 9
    for table in expected_tables:
        assert table in tables, f"Table '{table}' not found in {tables}"


def test_translation_record_create_validation_source_lang_too_long():
    """TranslationRecordCreate should reject source_lang > 10 chars."""
    import pytest
    from pydantic import ValidationError
    from backend.schemas import TranslationRecordCreate
    with pytest.raises(ValidationError):
        TranslationRecordCreate(
            meeting_id=1, seat_id=1,
            source_lang="a" * 11,
            target_lang="en",
            source_text="hello",
            translated_text="nihao",
        )


def test_translation_record_create_validation_target_lang_too_long():
    """TranslationRecordCreate should reject target_lang > 10 chars."""
    import pytest
    from pydantic import ValidationError
    from backend.schemas import TranslationRecordCreate
    with pytest.raises(ValidationError):
        TranslationRecordCreate(
            meeting_id=1, seat_id=1,
            source_lang="zh",
            target_lang="b" * 11,
            source_text="hello",
            translated_text="nihao",
        )


def test_translation_record_create_validation_empty_source_text():
    """TranslationRecordCreate should reject empty source_text."""
    import pytest
    from pydantic import ValidationError
    from backend.schemas import TranslationRecordCreate
    with pytest.raises(ValidationError):
        TranslationRecordCreate(
            meeting_id=1, seat_id=1,
            source_lang="zh",
            target_lang="en",
            source_text="",
            translated_text="nihao",
        )


def test_translation_record_create_validation_empty_translated_text():
    """TranslationRecordCreate should reject empty translated_text."""
    import pytest
    from pydantic import ValidationError
    from backend.schemas import TranslationRecordCreate
    with pytest.raises(ValidationError):
        TranslationRecordCreate(
            meeting_id=1, seat_id=1,
            source_lang="zh",
            target_lang="en",
            source_text="hello",
            translated_text="",
        )


def test_vote_cast_still_importable():
    """Original VoteCast schema must remain importable for routers."""
    from backend.schemas import VoteCast
    v = VoteCast(attendee_id=1, option="agree")
    assert v.attendee_id == 1
    assert v.option == "agree"


def test_service_call_create_still_importable():
    """Original ServiceCallCreate schema must remain importable for routers."""
    from backend.schemas import ServiceCallCreate
    s = ServiceCallCreate(seat_id=3, service_type="coffee")
    assert s.seat_id == 3
    assert s.service_type == "coffee"


def test_vote_cast_request_removed():
    """VoteCastRequest (duplicate of VoteCast) should not exist."""
    import pytest
    with pytest.raises(ImportError):
        from backend.schemas import VoteCastRequest


def test_service_call_create_request_removed():
    """ServiceCallCreateRequest (near-duplicate with unsupported custom_text) should not exist."""
    import pytest
    with pytest.raises(ImportError):
        from backend.schemas import ServiceCallCreateRequest


# ── CR-006: SeatState naming collision fix ──
def test_schemas_seatstate_ws_exists():
    """WS SeatState should be renamed to SeatStateWS to avoid collision with ORM SeatState."""
    from backend.schemas import SeatStateWS
    s = SeatStateWS(seat_id=1)
    assert s.seat_id == 1
    assert s.occupied is False
    assert s.checked_in is False
    assert s.attendee_name == ""


def test_schemas_seatstate_not_colliding_with_orm():
    """schemas.SeatState should not exist (renamed to SeatStateWS to avoid ORM collision)."""
    import pytest
    with pytest.raises(ImportError):
        from backend.schemas import SeatState


# ── CR-007: Vote is_anonymous column ──
def test_vote_model_has_is_anonymous_column():
    """Vote model should have is_anonymous column matching VoteCreateRequest schema."""
    from backend.models import Vote
    cols = {c.name for c in Vote.__table__.columns}
    assert "is_anonymous" in cols


def test_vote_is_anonymous_default():
    """Vote.is_anonymous column default is False (applied at INSERT time per SQLAlchemy)."""
    from backend.models import Vote
    from sqlalchemy import Boolean
    col = Vote.__table__.columns["is_anonymous"]
    assert isinstance(col.type, Boolean)
    assert col.default is not None
    assert col.default.arg is False
