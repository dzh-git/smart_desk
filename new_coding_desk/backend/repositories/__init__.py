"""
Repository layer — sole database access point.

Per system_architecture §4.3, DATABASE_SCHEMA §1 D2:
    - Each table belongs to exactly one Repository.
    - Repositories contain NO business logic.
"""
from backend.repositories.base import BaseRepository
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.repositories.translation_repository import TranslationRepository
from backend.repositories.vote_repository import VoteRepository

__all__ = ["BaseRepository", "MeetingRepository", "AttendeeRepository", "SeatRepository", "ServiceCallRepository", "TranslationRepository", "VoteRepository"]
