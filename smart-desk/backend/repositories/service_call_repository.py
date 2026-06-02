from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from backend.models import ServiceCall


class ServiceCallRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, meeting_id: int, seat_id: int, service_type: str, custom_text: str | None = None, attendee_id: int | None = None) -> ServiceCall:
        sc = ServiceCall(
            meeting_id=meeting_id, seat_id=seat_id,
            service_type=service_type, custom_text=custom_text, status="pending",
            attendee_id=attendee_id,
        )
        self.db.add(sc)
        self.db.commit()
        self.db.refresh(sc)
        return sc

    def get_by_id(self, call_id: int) -> ServiceCall | None:
        return self.db.query(ServiceCall).filter(ServiceCall.id == call_id).first()

    def list_by_meeting(self, meeting_id: int) -> list[ServiceCall]:
        return self.db.query(ServiceCall).filter(
            ServiceCall.meeting_id == meeting_id
        ).order_by(ServiceCall.created_at.desc()).all()

    def get_pending_by_seat(self, meeting_id: int, seat_id: int) -> ServiceCall | None:
        return self.db.query(ServiceCall).filter(
            ServiceCall.meeting_id == meeting_id,
            ServiceCall.seat_id == seat_id,
            ServiceCall.status == "pending"
        ).first()

    def get_pending_all(self, meeting_id: int) -> list[ServiceCall]:
        return self.db.query(ServiceCall).filter(
            ServiceCall.meeting_id == meeting_id, ServiceCall.status == "pending"
        ).all()

    def resolve(self, call_id: int) -> ServiceCall | None:
        sc = self.get_by_id(call_id)
        if sc:
            sc.status = "resolved"
            sc.resolved_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(sc)
        return sc

    def cancel(self, call_id: int, reason: str = "manual") -> ServiceCall | None:
        sc = self.get_by_id(call_id)
        if sc:
            sc.status = "cancelled"
            sc.cancel_reason = reason
            self.db.commit()
            self.db.refresh(sc)
        return sc

    def cancel_expired(self, timeout_seconds: int = 300) -> list[ServiceCall]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        expired = self.db.query(ServiceCall).filter(
            ServiceCall.status == "pending",
            ServiceCall.created_at < cutoff,
        ).all()
        for sc in expired:
            sc.status = "cancelled"
            sc.cancel_reason = "TIMEOUT"
        if expired:
            self.db.commit()
        return expired
