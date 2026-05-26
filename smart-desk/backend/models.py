import json
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from backend.database import Base


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(String(20), default="pending")  # pending / active / finished
    created_at = Column(DateTime, default=datetime.utcnow)

    agendas = relationship("Agenda", back_populates="meeting", cascade="all, delete-orphan")
    attendees = relationship("Attendee", back_populates="meeting", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="meeting", cascade="all, delete-orphan")


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
    service_type = Column(String(50), nullable=False)  # coffee / tea / water / other
    status = Column(String(20), default="pending")  # pending / acknowledged / completed
    created_at = Column(DateTime, default=datetime.utcnow)
