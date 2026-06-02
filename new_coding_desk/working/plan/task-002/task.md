# Task 002: Add Missing ORM Models (SeatState, SpeakerSeat, TranslationRecord)

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Add three missing ORM models to `backend/models.py`: `SeatState`, `SpeakerSeat`, `TranslationRecord`. These are needed by the Repository and Service layers before any refactoring can begin. Also update `database.py` seed logic to create seat_states (1-10) and speaker_seat (id=1) on startup.

This is Task 2 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\backend\models.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\main.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\schemas.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_models.py`

- [ ] **Step 1: Write the failing test — TranslationRecord model exists**

```python
# tests/test_models.py
import pytest
from backend.models import TranslationRecord, SeatState, SpeakerSeat


def test_translation_record_columns():
    """Verify TranslationRecord has the required columns."""
    cols = {c.name for c in TranslationRecord.__table__.columns}
    assert "id" in cols
    assert "meeting_id" in cols
    assert "seat_id" in cols
    assert "source_lang" in cols
    assert "target_lang" in cols
    assert "source_text" in cols
    assert "translated_text" in cols
    assert "created_at" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_translation_record_columns -v`
Expected: FAIL with ImportError (TranslationRecord not defined)

- [ ] **Step 3: Add TranslationRecord to models.py**

In `backend/models.py`, add after the ServiceCall class:
```python
class TranslationRecord(Base):
    __tablename__ = "translation_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    seat_id = Column(Integer, nullable=False)
    source_lang = Column(String(10), nullable=False)
    target_lang = Column(String(10), nullable=False)
    source_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
```

Also update the Meeting model to include the translation_records relationship:
```python
translation_records = relationship("TranslationRecord", back_populates="meeting", cascade="all, delete-orphan")
```

And add the back-reference in TranslationRecord:
```python
meeting = relationship("Meeting", back_populates="translation_records")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py::test_translation_record_columns -v`
Expected: PASS

- [ ] **Step 5: Write failing test — SeatState columns**

```python
def test_seat_state_columns():
    cols = {c.name for c in SeatState.__table__.columns}
    assert "seat_id" in cols
    assert "status" in cols
    assert "attendee_id" in cols
    assert "updated_at" in cols

def test_seat_state_defaults():
    s = SeatState(seat_id=1)
    assert s.status == "vacant"
    assert s.attendee_id is None
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_models.py::test_seat_state_columns tests/test_models.py::test_seat_state_defaults -v`
Expected: FAIL with ImportError

- [ ] **Step 7: Add SeatState to models.py**

```python
class SeatState(Base):
    __tablename__ = "seat_states"

    seat_id = Column(Integer, primary_key=True)  # 1-10, no autoincrement
    status = Column(String(30), default="vacant")  # vacant | occupied_unchecked | checked_in
    attendee_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_models.py::test_seat_state_columns tests/test_models.py::test_seat_state_defaults -v`
Expected: PASS

- [ ] **Step 9: Write failing test — SpeakerSeat columns**

```python
def test_speaker_seat_columns():
    cols = {c.name for c in SpeakerSeat.__table__.columns}
    assert "id" in cols
    assert "seat_id" in cols
    assert "updated_at" in cols

def test_speaker_seat_defaults():
    s = SpeakerSeat(id=1)
    assert s.seat_id is None
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `pytest tests/test_models.py::test_speaker_seat_columns tests/test_models.py::test_speaker_seat_defaults -v`
Expected: FAIL

- [ ] **Step 11: Add SpeakerSeat to models.py**

```python
class SpeakerSeat(Base):
    __tablename__ = "speaker_seat"

    id = Column(Integer, primary_key=True)  # always 1, single-row table
    seat_id = Column(Integer, nullable=True)  # NULL = no speaker seat
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `pytest tests/test_models.py::test_speaker_seat_columns tests/test_models.py::test_speaker_seat_defaults -v`
Expected: PASS

- [ ] **Step 13: Write failing test — Meeting model relationships updated**

```python
def test_meeting_has_translation_records_relationship():
    from backend.models import Meeting
    rels = {r.key for r in Meeting.__mapper__.relationships}
    assert "translation_records" in rels
```

- [ ] **Step 14: Run test**

Run: `pytest tests/test_models.py::test_meeting_has_translation_records_relationship -v`
Expected: PASS (already added in Step 3)

- [ ] **Step 15: Add all schemas for routers and services**

Add to `backend/schemas.py`:

```python
from datetime import datetime
from pydantic import BaseModel, Field

# ── Translation ──
class TranslationRecordCreate(BaseModel):
    meeting_id: int
    seat_id: int
    source_lang: str
    target_lang: str
    source_text: str
    translated_text: str

class TranslationRecordOut(BaseModel):
    id: int
    meeting_id: int
    seat_id: int
    source_lang: str
    target_lang: str
    source_text: str
    translated_text: str
    created_at: datetime
    model_config = {"from_attributes": True}

class TextTranslateRequest(BaseModel):
    text: str

# ── Seat ──
class SeatStateOut(BaseModel):
    seat_id: int
    status: str
    attendee_id: int | None
    updated_at: datetime
    model_config = {"from_attributes": True}

class SpeakerSeatOut(BaseModel):
    id: int
    seat_id: int | None
    updated_at: datetime
    model_config = {"from_attributes": True}

class SpeakerSeatSet(BaseModel):
    seat_id: int = Field(..., ge=0, le=10)  # 0 = clear

# ── Meeting ──
class MeetingCreate(BaseModel):
    title: str = Field(..., max_length=500)
    description: str = ""

class MeetingUpdate(BaseModel):
    title: str | None = None
    description: str | None = None

class MeetingOut(BaseModel):
    id: int
    title: str
    description: str
    status: str
    created_at: datetime
    attendee_count: int = 0
    checked_in_count: int = 0
    model_config = {"from_attributes": True}

# ── Agenda ──
class AgendaCreate(BaseModel):
    title: str = Field(..., max_length=500)
    sort_order: int = 0

class AgendaOut(BaseModel):
    id: int
    meeting_id: int
    title: str
    sort_order: int
    model_config = {"from_attributes": True}

# ── Attendee ──
class AttendeeCreate(BaseModel):
    name: str = Field(..., max_length=200)
    title: str = ""
    seat_id: int | None = Field(None, ge=1, le=10)

class AttendeeOut(BaseModel):
    id: int
    meeting_id: int
    name: str
    title: str | None
    seat_id: int | None
    checked_in: bool
    model_config = {"from_attributes": True}

# ── Vote ──
class VoteCreateRequest(BaseModel):
    meeting_id: int
    title: str = Field(..., max_length=500)
    options: list[str] = Field(..., min_length=2)
    is_anonymous: bool = False

class VoteCastRequest(BaseModel):
    attendee_id: int
    option: str

# ── Service Call ──
class ServiceCallCreateRequest(BaseModel):
    seat_id: int = Field(..., ge=1, le=10)
    service_type: str = Field(..., pattern="^(coffee|tea|water|other)$")
    custom_text: str | None = None
```

- [ ] **Step 16: Update seed data in main.py**

In `backend/main.py`, update the `_seed_demo` function (or add a new `_seed_system_data` function) to insert seat_state rows and speaker_seat row:
```python
def _seed_system_data():
    from backend.models import SeatState, SpeakerSeat
    db = SessionLocal()
    try:
        # Seed seat_states 1-10
        for sid in range(1, 11):
            existing = db.query(SeatState).filter(SeatState.seat_id == sid).first()
            if not existing:
                db.add(SeatState(seat_id=sid, status="vacant"))

        # Seed speaker_seat single row
        existing_sp = db.query(SpeakerSeat).filter(SpeakerSeat.id == 1).first()
        if not existing_sp:
            db.add(SpeakerSeat(id=1, seat_id=None))

        db.commit()
    finally:
        db.close()
```

Call `_seed_system_data()` in the lifespan function, right after `Base.metadata.create_all(bind=engine)`.

- [ ] **Step 17: Write integration test — models create tables**

```python
def test_models_create_all_tables():
    """Verify all 9 tables (including new ones) exist after create_all."""
    from backend.database import engine, Base
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "translation_records" in tables
    assert "seat_states" in tables
    assert "speaker_seat" in tables
```

Run: `pytest tests/test_models.py::test_models_create_all_tables -v`
Expected: PASS

- [ ] **Step 18: Run all model tests**

Run: `pytest tests/test_models.py -v`
Expected: All PASS
