"""
ORM models — per DATABASE_SCHEMA.md.

Package structure mirrors Repository ownership (§15):
    meeting.py          → MeetingRepository  (meetings, agendas)
    agenda.py           → MeetingRepository  (agendas)
    attendee.py         → AttendeeRepository (attendees)
    seat_state.py       → SeatRepository     (seat_states)
    speaker_seat.py     → SeatRepository     (speaker_seat)
    vote.py             → VoteRepository     (votes)
    vote_record.py      → VoteRepository     (vote_records)
    service_call.py     → ServiceCallRepository (service_calls)
    translation_record.py → TranslationRepository (translation_records)

Total: 10 tables.
"""
from backend.models.person import Person
from backend.models.meeting import Meeting
from backend.models.agenda import Agenda
from backend.models.attendee import Attendee
from backend.models.seat_state import SeatState
from backend.models.speaker_seat import SpeakerSeat
from backend.models.vote import Vote
from backend.models.vote_record import VoteRecord
from backend.models.service_call import ServiceCall
from backend.models.translation_record import TranslationRecord

__all__ = [
    "Meeting",
    "Person",
    "Agenda",
    "Attendee",
    "SeatState",
    "SpeakerSeat",
    "Vote",
    "VoteRecord",
    "ServiceCall",
    "TranslationRecord",
]
