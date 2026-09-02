"""Business rules for stable people identities."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.events.event_bus import EventBus
from backend.exceptions import ConflictError
from backend.models.person import Person
from backend.repositories.person_repository import PersonRepository
from backend.services.base import BaseService


class PersonService(BaseService):
    def __init__(self, db: Session, event_bus: EventBus) -> None:
        super().__init__(db, event_bus)
        self.person_repo = PersonRepository(db)

    def create_person(self, person_id: str, name: str) -> Person:
        if self.person_repo.get_by_id(person_id) is not None:
            raise ConflictError(
                f"Person {person_id} already exists",
                "PERSON_ALREADY_EXISTS",
            )
        return self.person_repo.create(id=person_id, name=name)

    def list_people(self) -> list[Person]:
        return self.person_repo.list_all()
