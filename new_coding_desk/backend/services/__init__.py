"""
Service layer — all business logic lives here.

Per system_architecture §4.2, EVENT_BUS_SPEC §2 E1:
    - Services contain all business rules.
    - Services publish events via EventBus.
    - Services call Repositories for data access.
    - Services NEVER access WebSocket directly.
"""
from backend.services.base import BaseService
from backend.services.meeting_service import MeetingService
from backend.services.seat_service import SeatService
from backend.services.service_call_service import ServiceCallService
from backend.services.translation_service import TranslationService

__all__ = ["BaseService", "MeetingService", "SeatService", "ServiceCallService", "TranslationService"]
