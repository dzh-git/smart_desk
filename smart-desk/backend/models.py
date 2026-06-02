import json
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.database import Base


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(String(20), default="pending")  # pending / active / finished
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    agendas = relationship("Agenda", back_populates="meeting", cascade="all, delete-orphan")
    attendees = relationship("Attendee", back_populates="meeting", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="meeting", cascade="all, delete-orphan")
    translation_records = relationship("TranslationRecord", back_populates="meeting", cascade="all, delete-orphan")


class Agenda(Base):
    __tablename__ = "agendas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    title = Column(String(500), nullable=False)
    sort_order = Column(Integer, default=0)

    meeting = relationship("Meeting", back_populates="agendas")


class Attendee(Base):
    __tablename__ = "attendees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    name = Column(String(100), nullable=False)
    title = Column(String(100), default="")
    checked_in = Column(Boolean, default=False)
    seat_id = Column(Integer, default=0)

    meeting = relationship("Meeting", back_populates="attendees")


class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    title = Column(String(500), nullable=False)
    options_json = Column(Text, default="[]")  # JSON array of option strings
    status = Column(String(20), default="open")  # open / closed
    is_anonymous = Column(Boolean, default=False)
    closed_at = Column(DateTime, nullable=True)

    meeting = relationship("Meeting", back_populates="votes")
    records = relationship("VoteRecord", back_populates="vote", cascade="all, delete-orphan")

    @property
    def options(self):
        return json.loads(self.options_json)

    @options.setter
    def options(self, value):
        self.options_json = json.dumps(value, ensure_ascii=False)


class VoteRecord(Base):
    __tablename__ = "vote_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vote_id = Column(Integer, ForeignKey("votes.id"), nullable=False)
    attendee_id = Column(Integer, ForeignKey("attendees.id"), nullable=False)
    option = Column(String(200), nullable=False)

    vote = relationship("Vote", back_populates="records")


class ServiceCall(Base):
    __tablename__ = "service_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    seat_id = Column(Integer, default=1)
    attendee_id = Column(Integer, ForeignKey("attendees.id"), nullable=True)
    service_type = Column(String(50), nullable=False)  # coffee / tea / water / other
    custom_text = Column(Text, nullable=True)  # used when service_type='other'
    status = Column(String(20), default="pending")  # pending / resolved / cancelled
    cancel_reason = Column(String(50), nullable=True)  # TIMEOUT | manual
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime, nullable=True)


class TranslationRecord(Base):
    __tablename__ = "translation_records"
    __table_args__ = (
        UniqueConstraint('meeting_id', 'seat_id', 'source_lang', 'target_lang', 'source_text',
                         name='uq_translation_record'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    seat_id = Column(Integer, nullable=False)
    source_lang = Column(String(10), nullable=False)
    target_lang = Column(String(10), nullable=False)
    source_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    meeting = relationship("Meeting", back_populates="translation_records")


class SeatState(Base):
    __tablename__ = "seat_states"

    seat_id = Column(Integer, primary_key=True)  # 1-10, no autoincrement
    status = Column(String(30), default="vacant")  # vacant | occupied_unchecked | checked_in
    attendee_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __init__(self, **kwargs):
        kwargs.setdefault("status", "vacant")
        super().__init__(**kwargs)


class SpeakerSeat(Base):
    __tablename__ = "speaker_seat"

    id = Column(Integer, primary_key=True)  # always 1, single-row table
    seat_id = Column(Integer, nullable=True)  # NULL = no speaker seat
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
