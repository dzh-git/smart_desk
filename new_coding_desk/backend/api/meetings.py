"""
Meeting API — meeting CRUD, agendas, attendees.

Per API_SPEC §4-6:
    GET    /api/meetings                        → MeetingService
    POST   /api/meetings                        → MeetingService
    GET    /api/meetings/active                 → MeetingService
    GET    /api/meetings/{meeting_id}           → MeetingService
    POST   /api/meetings/{meeting_id}/start     → MeetingService  + meeting_started event
    POST   /api/meetings/{meeting_id}/end       → MeetingService  + meeting_ended event

    GET    /api/meetings/{meeting_id}/agendas   → MeetingService
    POST   /api/meetings/{meeting_id}/agendas   → MeetingService
    DELETE /api/meetings/{meeting_id}/agendas/{agenda_id} → MeetingService

    GET    /api/meetings/{meeting_id}/attendees → MeetingService
    POST   /api/meetings/{meeting_id}/attendees → MeetingService
    DELETE /api/meetings/{meeting_id}/attendees/{attendee_id} → MeetingService
"""
from __future__ import annotations

from typing import List, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.meeting import (
    MeetingCreate,
    MeetingResponse,
    AgendaCreate,
    AgendaResponse,
    AttendeeCreate,
    AttendeeResponse,
    SeatAssignmentRequest,
)
from backend.services.meeting_service import MeetingService

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _service(db: Session) -> MeetingService:
    return MeetingService(db, event_bus)


def _to_json(api_response: ApiResponse, status_code: int = 200) -> JSONResponse:
    """Serialize ApiResponse to JSONResponse with the given HTTP status."""
    return JSONResponse(
        content=api_response.model_dump(),
        status_code=status_code,
    )


# ── Meeting CRUD ─────────────────────────────────────────────────────────────


@router.get("", response_model=ApiResponse[List[MeetingResponse]])
def list_meetings(
    status: Literal["pending", "active", "finished"] | None = None,
    db: Session = Depends(get_db),
):
    """GET /api/meetings — list meetings, optionally filtered by status."""
    meetings = _service(db).list_meetings(status=status)
    return ApiResponse.ok(
        data=[MeetingResponse.model_validate(m) for m in meetings]
    )


@router.post("", response_model=ApiResponse[MeetingResponse], status_code=201)
def create_meeting(body: MeetingCreate, db: Session = Depends(get_db)):
    """POST /api/meetings — create a new meeting."""
    meeting = _service(db).create_meeting(
        title=body.title, description=body.description
    )
    return ApiResponse.ok(data=MeetingResponse.model_validate(meeting))


@router.get("/active", response_model=ApiResponse[MeetingResponse])
def get_active_meeting(db: Session = Depends(get_db)):
    """GET /api/meetings/active — get the currently active meeting."""
    meeting = _service(db).get_active_meeting()
    return ApiResponse.ok(
        data=MeetingResponse.model_validate(meeting) if meeting else None
    )


@router.get("/{meeting_id}", response_model=ApiResponse[MeetingResponse])
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """GET /api/meetings/{meeting_id} — get a meeting by ID."""
    try:
        meeting = _service(db).get_meeting(meeting_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    return ApiResponse.ok(data=MeetingResponse.model_validate(meeting))


# ── Meeting lifecycle ────────────────────────────────────────────────────────


@router.post("/{meeting_id}/start", response_model=ApiResponse[MeetingResponse])
def start_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """POST /api/meetings/{meeting_id}/start — start a meeting.

    Publishes: meeting_started event.
    """
    svc = _service(db)
    try:
        meeting = svc.start_meeting(meeting_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ConflictError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 409)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=MeetingResponse.model_validate(meeting))


@router.post("/{meeting_id}/end", response_model=ApiResponse[MeetingResponse])
def end_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """POST /api/meetings/{meeting_id}/end — end an active meeting.

    Publishes: meeting_ended event.
    """
    svc = _service(db)
    try:
        meeting = svc.end_meeting(meeting_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=MeetingResponse.model_validate(meeting))


# ── Agenda ───────────────────────────────────────────────────────────────────


@router.get(
    "/{meeting_id}/agendas", response_model=ApiResponse[List[AgendaResponse]]
)
def list_agendas(meeting_id: int, db: Session = Depends(get_db)):
    """GET /api/meetings/{meeting_id}/agendas — list agendas."""
    try:
        agendas = _service(db).list_agendas(meeting_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    return ApiResponse.ok(
        data=[AgendaResponse.model_validate(a) for a in agendas]
    )


@router.post(
    "/{meeting_id}/agendas", response_model=ApiResponse[AgendaResponse]
)
def create_agenda(
    meeting_id: int, body: AgendaCreate, db: Session = Depends(get_db)
):
    """POST /api/meetings/{meeting_id}/agendas — add an agenda item (pending).

    Meeting must be active. Publishes agenda_updated event.
    """
    svc = _service(db)
    try:
        agenda = svc.create_agenda(
            meeting_id=meeting_id,
            title=body.title,
            sort_order=body.sort_order,
        )
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=AgendaResponse.model_validate(agenda))


@router.delete(
    "/{meeting_id}/agendas/{agenda_id}", response_model=ApiResponse[None]
)
def delete_agenda(
    meeting_id: int, agenda_id: int, db: Session = Depends(get_db)
):
    """DELETE /api/meetings/{meeting_id}/agendas/{agenda_id} — remove a non-active agenda.

    Meeting must be active. Cannot delete an active agenda.
    """
    try:
        _service(db).delete_agenda(meeting_id, agenda_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(message="Agenda deleted")


# ── Agenda State Machine (Phase 1) ─────────────────────────────────────────


@router.post(
    "/{meeting_id}/agendas/{agenda_id}/set-current",
    response_model=ApiResponse[AgendaResponse],
)
def set_current_agenda(
    meeting_id: int, agenda_id: int, db: Session = Depends(get_db)
):
    """POST /{meeting_id}/agendas/{agenda_id}/set-current — set as active topic.

    Only pending or skipped accepted. Completed → 400.
    Idempotent if already active. Switches if another active exists.
    """
    svc = _service(db)
    try:
        agenda = svc.set_current_agenda(meeting_id, agenda_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=AgendaResponse.model_validate(agenda))


@router.post(
    "/{meeting_id}/agendas/advance",
    response_model=ApiResponse[AgendaResponse],
)
def advance_agenda(
    meeting_id: int, db: Session = Depends(get_db)
):
    """POST /{meeting_id}/agendas/advance — complete current, activate next pending.

    Requires an active agenda (400 otherwise).
    If no next pending, current is completed with no current agenda.
    """
    svc = _service(db)
    try:
        result = svc.advance_agenda(meeting_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    if result is None:
        return ApiResponse.ok(data=None)
    return ApiResponse.ok(data=AgendaResponse.model_validate(result))


@router.post(
    "/{meeting_id}/agendas/{agenda_id}/complete",
    response_model=ApiResponse[AgendaResponse],
)
def complete_agenda(
    meeting_id: int, agenda_id: int, db: Session = Depends(get_db)
):
    """POST /{meeting_id}/agendas/{agenda_id}/complete — complete current active.

    agenda_id must be the current active (400 otherwise).
    """
    svc = _service(db)
    try:
        agenda = svc.complete_agenda(meeting_id, agenda_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=AgendaResponse.model_validate(agenda))


@router.post(
    "/{meeting_id}/agendas/{agenda_id}/skip",
    response_model=ApiResponse[AgendaResponse],
)
def skip_agenda(
    meeting_id: int, agenda_id: int, db: Session = Depends(get_db)
):
    """POST /{meeting_id}/agendas/{agenda_id}/skip — skip current active.

    agenda_id must be the current active (400 otherwise).
    """
    svc = _service(db)
    try:
        agenda = svc.skip_agenda(meeting_id, agenda_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=AgendaResponse.model_validate(agenda))


# ── Attendee ─────────────────────────────────────────────────────────────────


@router.get(
    "/{meeting_id}/attendees", response_model=ApiResponse[List[AttendeeResponse]]
)
def list_attendees(meeting_id: int, db: Session = Depends(get_db)):
    """GET /api/meetings/{meeting_id}/attendees — list attendees."""
    try:
        attendees = _service(db).list_attendees(meeting_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    return ApiResponse.ok(
        data=[AttendeeResponse.model_validate(a) for a in attendees]
    )


@router.post(
    "/{meeting_id}/attendees", response_model=ApiResponse[AttendeeResponse]
)
def create_attendee(
    meeting_id: int, body: AttendeeCreate, db: Session = Depends(get_db)
):
    """POST /api/meetings/{meeting_id}/attendees — add an attendee."""
    svc = _service(db)
    try:
        attendee = svc.create_attendee(
            meeting_id=meeting_id,
            name=body.name,
            title=body.title,
            person_id=body.person_id,
        )
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ConflictError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 409)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=AttendeeResponse.model_validate(attendee))


@router.put(
    "/{meeting_id}/seat-assignments/{seat_id}",
    response_model=ApiResponse[AttendeeResponse],
)
def set_seat_assignment(
    meeting_id: int,
    seat_id: int,
    body: SeatAssignmentRequest,
    db: Session = Depends(get_db),
):
    try:
        attendee = _service(db).assign_attendee_to_seat(
            meeting_id,
            seat_id,
            body.attendee_id,
        )
    except NotFoundError as error:
        return _to_json(ApiResponse.fail(error.message, error.error_code), 404)
    except ConflictError as error:
        return _to_json(ApiResponse.fail(error.message, error.error_code), 409)
    except ValidationError as error:
        return _to_json(ApiResponse.fail(error.message, error.error_code), 400)
    return ApiResponse.ok(data=AttendeeResponse.model_validate(attendee))


@router.delete(
    "/{meeting_id}/seat-assignments/{seat_id}",
    response_model=ApiResponse[None],
)
def clear_seat_assignment(
    meeting_id: int,
    seat_id: int,
    db: Session = Depends(get_db),
):
    try:
        _service(db).clear_seat_assignment(meeting_id, seat_id)
    except NotFoundError as error:
        return _to_json(ApiResponse.fail(error.message, error.error_code), 404)
    except ConflictError as error:
        return _to_json(ApiResponse.fail(error.message, error.error_code), 409)
    except ValidationError as error:
        return _to_json(ApiResponse.fail(error.message, error.error_code), 400)
    return ApiResponse.ok(message="Seat assignment cleared")


@router.delete(
    "/{meeting_id}/attendees/{attendee_id}", response_model=ApiResponse[None]
)
def delete_attendee(
    meeting_id: int, attendee_id: int, db: Session = Depends(get_db)
):
    """DELETE /api/meetings/{meeting_id}/attendees/{attendee_id} — remove an attendee."""
    try:
        _service(db).delete_attendee(meeting_id, attendee_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ConflictError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 409)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(message="Attendee deleted")
