from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.models import SeatState, SpeakerSeat


class SeatRepository:
    VALID_STATUSES = {"vacant", "occupied_unchecked", "checked_in"}

    def __init__(self, db: Session):
        self.db = db

    # -- Seat States --

    def get_seat_state(self, seat_id: int) -> SeatState | None:
        return self.db.query(SeatState).filter(SeatState.seat_id == seat_id).first()

    def get_all_seats(self) -> list[SeatState]:
        return self.db.query(SeatState).order_by(SeatState.seat_id).all()

    def update_seat(self, seat_id: int, status: str, attendee_id: int | None = None) -> SeatState | None:
        if status not in self.VALID_STATUSES:
            raise ValueError(
                f"Invalid status: {status!r}. Must be one of {sorted(self.VALID_STATUSES)}."
            )
        s = self.get_seat_state(seat_id)
        if s:
            s.status = status
            s.attendee_id = attendee_id
            s.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(s)
        return s

    def reset_all_seats(self) -> None:
        self.db.query(SeatState).update({
            "status": "vacant", "attendee_id": None,
            "updated_at": datetime.now(timezone.utc)
        })
        self.db.commit()

    # -- Speaker Seat --

    def get_speaker_seat(self) -> SpeakerSeat | None:
        return self.db.query(SpeakerSeat).filter(SpeakerSeat.id == 1).first()

    def set_speaker_seat(self, seat_id: int) -> SpeakerSeat | None:
        sp = self.get_speaker_seat()
        if sp:
            sp.seat_id = seat_id
            sp.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(sp)
        return sp

    def clear_speaker_seat(self) -> SpeakerSeat | None:
        sp = self.get_speaker_seat()
        if sp:
            sp.seat_id = None
            sp.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(sp)
        return sp
