"""Stable person identity API."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import ConflictError
from backend.schemas import ApiResponse
from backend.schemas.person import PersonCreate, PersonResponse
from backend.services.person_service import PersonService

router = APIRouter(prefix="/api/people", tags=["people"])


def _service(db: Session) -> PersonService:
    return PersonService(db, event_bus)


@router.get("", response_model=ApiResponse[List[PersonResponse]])
def list_people(db: Session = Depends(get_db)):
    people = _service(db).list_people()
    return ApiResponse.ok(
        data=[PersonResponse.model_validate(person) for person in people]
    )


@router.post(
    "",
    response_model=ApiResponse[PersonResponse],
    status_code=201,
)
def create_person(body: PersonCreate, db: Session = Depends(get_db)):
    try:
        person = _service(db).create_person(body.id, body.name)
    except ConflictError as error:
        return JSONResponse(
            content=ApiResponse.fail(
                error.message,
                error.error_code,
            ).model_dump(),
            status_code=409,
        )
    return ApiResponse.ok(data=PersonResponse.model_validate(person))
