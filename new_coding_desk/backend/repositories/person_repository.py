"""Persistence for stable people identities."""
from __future__ import annotations

from backend.models.person import Person
from backend.repositories.base import BaseRepository


class PersonRepository(BaseRepository[Person]):
    model = Person

    def get_by_id(self, person_id: str) -> Person | None:
        return self.db.get(Person, person_id)

    def list_all(self, *, offset: int = 0, limit: int = 200) -> list[Person]:
        return (
            self.db.query(Person)
            .order_by(Person.id)
            .offset(offset)
            .limit(limit)
            .all()
        )
