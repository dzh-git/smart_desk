from __future__ import annotations
from sqlalchemy.orm import Session


class DashboardService:
    """Aggregates meeting + speaker_seat + active_vote + pending_service_calls + seats."""

    def __init__(self, db: Session, meeting_repo, attendee_repo, seat_repo,
                 vote_repo, service_call_repo):
        self.db = db
        self.meeting_repo = meeting_repo
        self.attendee_repo = attendee_repo
        self.seat_repo = seat_repo
        self.vote_repo = vote_repo
        self.service_call_repo = service_call_repo

    def get_dashboard(self, meeting_id: int) -> dict:
        meeting = self.meeting_repo.get_by_id(meeting_id)
        speaker_seat = self.seat_repo.get_speaker_seat()
        active_vote = self.vote_repo.get_active(meeting_id)
        pending_calls = self.service_call_repo.get_pending_all(meeting_id)
        seats = self.seat_repo.get_all_seats()

        # Batch-fetch all attendees for this meeting to avoid N+1 queries (CR-007)
        attendees = self.attendee_repo.list_by_meeting(meeting_id)
        name_by_id: dict[int, str] = {a.id: a.name for a in attendees}

        return {
            "meeting": {
                "id": meeting.id, "title": meeting.title,
                "status": meeting.status, "created_at": str(meeting.created_at),
            } if meeting else None,
            "speaker_seat": speaker_seat.seat_id if speaker_seat else None,
            "active_vote": {
                "id": active_vote.id, "title": active_vote.title,
                "options": active_vote.options, "status": active_vote.status,
            } if active_vote else None,
            "pending_service_calls": [
                {"id": sc.id, "seat_id": sc.seat_id, "service_type": sc.service_type,
                 "custom_text": sc.custom_text, "created_at": str(sc.created_at)}
                for sc in pending_calls
            ],
            "seats": [
                {
                    "seat_id": s.seat_id,
                    "status": s.status,
                    "attendee_id": s.attendee_id,
                    "attendee_name": name_by_id.get(s.attendee_id) if s.attendee_id else None,
                }
                for s in seats
            ],
        }
