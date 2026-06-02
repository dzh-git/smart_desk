from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.models import Meeting, Agenda


class MeetingRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, title: str, description: str = "") -> Meeting:
        m = Meeting(title=title, description=description, status="pending")
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return m

    def get_by_id(self, meeting_id: int) -> Meeting | None:
        return self.db.query(Meeting).filter(Meeting.id == meeting_id).first()

    def list_all(self) -> list[Meeting]:
        return self.db.query(Meeting).order_by(Meeting.created_at.desc()).all()

    def get_active(self) -> Meeting | None:
        return self.db.query(Meeting).filter(
            Meeting.status == "active"
        ).order_by(Meeting.created_at.desc()).first()

    VALID_STATUSES = {"pending", "active", "finished"}

    def update_status(self, meeting_id: int, status: str) -> Meeting | None:
        if status not in self.VALID_STATUSES:
            raise ValueError(
                f"Invalid status: {status!r}. Must be one of {sorted(self.VALID_STATUSES)}."
            )
        m = self.get_by_id(meeting_id)
        if m:
            m.status = status
            if status == "active" and m.started_at is None:
                m.started_at = datetime.now(timezone.utc)
            elif status == "finished" and m.ended_at is None:
                m.ended_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(m)
        return m

    def delete(self, meeting_id: int) -> bool:
        m = self.get_by_id(meeting_id)
        if m:
            self.db.delete(m)
            self.db.commit()
            return True
        return False

    # Agenda methods
    def add_agenda(self, meeting_id: int, title: str, sort_order: int = 0) -> Agenda:
        a = Agenda(meeting_id=meeting_id, title=title, sort_order=sort_order)
        self.db.add(a)
        self.db.commit()
        self.db.refresh(a)
        return a

    def list_agendas(self, meeting_id: int) -> list[Agenda]:
        return self.db.query(Agenda).filter(
            Agenda.meeting_id == meeting_id
        ).order_by(Agenda.sort_order).all()

    def remove_agenda(self, meeting_id: int, agenda_id: int) -> bool:
        a = self.db.query(Agenda).filter(
            Agenda.id == agenda_id, Agenda.meeting_id == meeting_id
        ).first()
        if a:
            self.db.delete(a)
            self.db.commit()
            return True
        return False
