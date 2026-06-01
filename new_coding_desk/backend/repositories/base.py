"""
BaseRepository — generic CRUD template for all repositories.

Per system_architecture §4.3:
    - Only database access layer
    - No business logic
    - No EventBus access
    - No WebSocket access

Subclass and set `model` to the SQLAlchemy ORM class.

Usage:
    class MeetingRepository(BaseRepository[Meeting]):
        model = Meeting
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    """Generic CRUD repository.

    Subclass must set `model` to the SQLAlchemy model class.
    """

    model: type[ModelT]

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Create ──────────────────────────────────────────────────────────────

    def create(self, **kwargs: Any) -> ModelT:
        instance = self.model(**kwargs)
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    # ── Read ────────────────────────────────────────────────────────────────

    def get_by_id(self, id: int) -> ModelT | None:
        return self.db.get(self.model, id)

    def list_all(self, *, offset: int = 0, limit: int = 200) -> list[ModelT]:
        return (
            self.db.query(self.model)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count(self) -> int:
        return self.db.query(self.model).count()

    # ── Update ──────────────────────────────────────────────────────────────

    def save(self, instance: ModelT) -> ModelT:
        """Persist changes to an existing instance."""
        self.db.commit()
        self.db.refresh(instance)
        return instance

    # ── Delete ──────────────────────────────────────────────────────────────

    def delete(self, instance: ModelT) -> None:
        self.db.delete(instance)
        self.db.commit()
