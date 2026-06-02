from __future__ import annotations
from sqlalchemy.orm import Session
from backend.services.event_bus import EventBus, BaseEvent


class MeetingService:
    def __init__(self, db: Session, event_bus: EventBus,
                 meeting_repo, attendee_repo, seat_repo, vote_repo):
        # db accepted but not stored — all DB operations go through injected repositories
        self.bus = event_bus
        self.meeting_repo = meeting_repo
        self.attendee_repo = attendee_repo
        self.seat_repo = seat_repo
        self.vote_repo = vote_repo

    def create(self, title: str, description: str = ""):
        # Reject if an active meeting already exists (spec 4.5)
        if self.meeting_repo.get_active():
            return None  # ACTIVE_MEETING_EXISTS — caller returns 400
        return self.meeting_repo.create(title, description)

    def get_by_id(self, meeting_id: int):
        return self.meeting_repo.get_by_id(meeting_id)

    def list_all(self):
        return self.meeting_repo.list_all()

    def get_active(self):
        return self.meeting_repo.get_active()

    def start(self, meeting_id: int):
        """Start a meeting. Fires preload trigger + broadcast."""
        if self.meeting_repo.get_active():
            return None  # ACTIVE_MEETING_EXISTS handled by caller
        meeting = self.meeting_repo.get_by_id(meeting_id)
        if not meeting or meeting.status != "pending":
            return None  # Cannot start non-pending or non-existent meeting
        m = self.meeting_repo.update_status(meeting_id, "active")
        if m:
            self.bus.publish(BaseEvent(
                name="meeting_started",
                payload={"meeting_id": meeting_id},
            ))
        return m

    def end(self, meeting_id: int):
        """End meeting: reset seats, clear speaker seat, auto-close votes, broadcast."""
        meeting = self.meeting_repo.get_by_id(meeting_id)
        if not meeting or meeting.status != "active":
            return None  # Meeting not found or not in active state
        m = self.meeting_repo.update_status(meeting_id, "finished")
        if m:
            self.seat_repo.reset_all_seats()
            self.seat_repo.clear_speaker_seat()
            # Per spec 8.3/Q21: iterate open votes and publish individual vote_closed for each
            open_votes = self.vote_repo.get_all_open(meeting_id)
            for vote in open_votes:
                self.vote_repo.close(vote.id)
                self.bus.publish(BaseEvent(
                    name="vote_closed",
                    payload={"vote_id": vote.id, "meeting_id": meeting_id},
                ))
            self.bus.publish(BaseEvent(
                name="meeting_ended",
                payload={"meeting_id": meeting_id},
            ))
        return m

    def delete(self, meeting_id: int):
        """Delete a meeting. Rejects active meetings — must end() first."""
        meeting = self.meeting_repo.get_by_id(meeting_id)
        if not meeting:
            return False
        if meeting.status == "active":
            return False  # Cannot delete active meeting — end() first
        return self.meeting_repo.delete(meeting_id)

    # Agenda delegation
    def add_agenda(self, meeting_id: int, title: str, sort_order: int = 0):
        return self.meeting_repo.add_agenda(meeting_id, title, sort_order)

    def list_agendas(self, meeting_id: int):
        return self.meeting_repo.list_agendas(meeting_id)

    def remove_agenda(self, meeting_id: int, agenda_id: int):
        return self.meeting_repo.remove_agenda(meeting_id, agenda_id)

    # Attendee delegation
    def add_attendee(self, meeting_id: int, name: str, title: str = "", seat_id: int | None = None):
        return self.attendee_repo.create(meeting_id, name, title, seat_id)

    def list_attendees(self, meeting_id: int):
        return self.attendee_repo.list_by_meeting(meeting_id)

    def remove_attendee(self, meeting_id: int, attendee_id: int):
        # Guard: verify attendee exists and belongs to this meeting (CR-014)
        attendee = self.attendee_repo.get_by_id(attendee_id)
        if not attendee or attendee.meeting_id != meeting_id:
            return False  # ATTENDEE_NOT_IN_MEETING
        if self.attendee_repo.has_history(meeting_id, attendee_id):
            return False  # ATTENDEE_HAS_HISTORY
        return self.attendee_repo.delete(attendee_id)
