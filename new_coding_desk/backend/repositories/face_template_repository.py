"""Persistence helpers for encrypted face templates."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.models.face_template import FaceModelPolicy, FaceTemplate


class FaceTemplateRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, person_id: str) -> FaceTemplate | None:
        return self.db.get(FaceTemplate, person_id)

    def list_all(self) -> list[FaceTemplate]:
        return self.db.query(FaceTemplate).order_by(FaceTemplate.created_at).all()

    def count(self) -> int:
        return self.db.query(FaceTemplate).count()

    def save(self, template: FaceTemplate, *, commit: bool = True) -> FaceTemplate:
        self.db.add(template)
        if commit:
            self.db.commit()
            self.db.refresh(template)
        else:
            self.db.flush()
        return template

    def delete(self, template: FaceTemplate, *, commit: bool = True) -> None:
        self.db.delete(template)
        if commit:
            self.db.commit()
        else:
            self.db.flush()

    def get_policy(self, model_hash: str) -> FaceModelPolicy | None:
        return self.db.get(FaceModelPolicy, model_hash)

    def save_policy(self, policy: FaceModelPolicy, *, commit: bool = True) -> FaceModelPolicy:
        self.db.add(policy)
        if commit:
            self.db.commit()
            self.db.refresh(policy)
        else:
            self.db.flush()
        return policy
