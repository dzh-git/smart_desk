"""Central face-template library, meeting assignment, and tablet sync."""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session

from backend.exceptions import ConflictError, NotFoundError, ValidationError
from backend.models.attendee import Attendee
from backend.models.face_template import FaceModelPolicy, FaceTemplate
from backend.models.meeting import Meeting
from backend.models.person import Person
from backend.models.seat_state import SeatState
from backend.repositories.face_template_repository import FaceTemplateRepository
from backend.schemas.face_template import (
    FaceSeatAssignmentItem,
    FaceSeatAssignmentUpdate,
    FaceSeatAssignmentsResponse,
    FaceTemplateLibraryResponse,
    FaceTemplateSaveResult,
    FaceTemplateSummary,
)
from backend.security.face_template_crypto import FaceTemplateCrypto
from backend.services.tablet_device_service import TabletDeviceService

TEMPLATE_CAPACITY = 81
ALL_FACE_SEATS = tuple(range(1, 10))
PARTICIPANT_SEATS = tuple(range(2, 10))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FaceTemplateService:
    def __init__(
        self,
        db: Session,
        crypto: FaceTemplateCrypto | None = None,
    ) -> None:
        self.db = db
        self.repo = FaceTemplateRepository(db)
        self.crypto = crypto or FaceTemplateCrypto()

    def authenticate_host(
        self,
        *,
        device_id: str,
        token: str | None,
    ):
        try:
            return TabletDeviceService(self.db).authenticate(
                device_id=device_id,
                seat_id=1,
                token=token,
            )
        except (NotFoundError, ValidationError) as error:
            raise ValidationError(
                "Face template management requires the bound Seat 1 tablet",
                "HOST_DEVICE_REQUIRED",
            ) from error

    def server_transport_key(self) -> str:
        return self.crypto.server_public_key_pem()

    def list_library(self) -> FaceTemplateLibraryResponse:
        items = [self._summary(template) for template in self.repo.list_all()]
        return FaceTemplateLibraryResponse(
            capacity=TEMPLATE_CAPACITY,
            count=len(items),
            templates=items,
        )

    def save_encrypted_upload(
        self,
        *,
        person_id: str,
        envelope: dict[str, str],
    ) -> FaceTemplateSaveResult:
        person = self.db.get(Person, person_id)
        if person is None or not person.active:
            raise NotFoundError(
                f"Person {person_id} not found or inactive",
                "PERSON_NOT_FOUND",
            )
        try:
            payload = self.crypto.decrypt_upload_envelope(envelope)
        except Exception as error:
            raise ValidationError(
                "Unable to decrypt the host tablet face template",
                "FACE_TEMPLATE_DECRYPT_FAILED",
            ) from error
        self._validate_payload(payload, person_id=person_id)
        if self.repo.count() > 0:
            try:
                self.crypto.require_at_rest_key()
            except RuntimeError as error:
                raise ValidationError(
                    "The central face-template encryption key is missing or invalid",
                    "FACE_TEMPLATE_KEY_MISSING",
                ) from error

        existing = self.repo.get(person_id)
        model_hash = str(payload["modelHash"])
        other_model = next(
            (
                item
                for item in self.repo.list_all()
                if item.person_id != person_id and item.model_hash != model_hash
            ),
            None,
        )
        if other_model is not None:
            raise ConflictError(
                "The central library contains templates from another model version",
                "FACE_MODEL_MISMATCH",
            )

        evicted: FaceTemplate | None = None
        evicted_name: str | None = None
        if existing is None and self.repo.count() >= TEMPLATE_CAPACITY:
            protected = self._protected_person_ids()
            evicted = next(
                (
                    item
                    for item in self.repo.list_all()
                    if item.person_id not in protected
                ),
                None,
            )
            if evicted is None:
                raise ConflictError(
                    "All 81 templates are protected by pending or active meetings",
                    "FACE_TEMPLATE_CAPACITY_LOCKED",
                )
            evicted_person = self.db.get(Person, evicted.person_id)
            evicted_name = evicted_person.name if evicted_person else evicted.person_id
            self.repo.delete(evicted, commit=False)

        now = _utcnow()
        template = existing or FaceTemplate(person_id=person_id, created_at=now)
        template.model_version = str(payload["modelVersion"])
        template.model_hash = model_hash
        template.pipeline_version = int(payload["pipelineVersion"])
        template.embedding_dimension = int(payload["embeddingDimension"])
        template.normal_sample_count = int(payload["normalSampleCount"])
        template.fill_light_sample_count = int(payload["fillLightSampleCount"])
        template.encrypted_payload = self.crypto.encrypt_at_rest(payload)
        template.revision = (existing.revision + 1) if existing else 1
        template.updated_at = now
        self.repo.save(template, commit=False)

        threshold = float(payload["threshold"])
        policy = self.repo.get_policy(model_hash) or FaceModelPolicy(
            model_hash=model_hash
        )
        policy.model_version = template.model_version
        policy.pipeline_version = template.pipeline_version
        policy.threshold = threshold
        policy.threshold_status = str(payload["thresholdStatus"])
        policy.updated_at = now
        self.repo.save_policy(policy, commit=False)

        self._bump_revisions_for_person(person_id)
        if evicted is not None:
            self._bump_revisions_for_person(evicted.person_id)
        self.db.commit()
        self.db.refresh(template)
        return FaceTemplateSaveResult(
            template=self._summary(template),
            evictedPersonId=evicted.person_id if evicted else None,
            evictedPersonName=evicted_name,
        )

    def delete_template(self, person_id: str) -> None:
        template = self.repo.get(person_id)
        if template is None:
            raise NotFoundError(
                f"Face template {person_id} not found",
                "FACE_TEMPLATE_NOT_FOUND",
            )
        if person_id in self._protected_person_ids():
            raise ConflictError(
                "The template is assigned to a pending or active meeting",
                "FACE_TEMPLATE_IN_USE",
            )
        self.repo.delete(template)

    def get_assignments(self, meeting_id: int) -> FaceSeatAssignmentsResponse:
        meeting = self.db.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError("Meeting not found", "MEETING_NOT_FOUND")
        attendees = {
            attendee.assigned_seat_id: attendee
            for attendee in self.db.query(Attendee).filter(
                Attendee.meeting_id == meeting_id,
                Attendee.assigned_seat_id.in_(ALL_FACE_SEATS),
            )
        }
        items: list[FaceSeatAssignmentItem] = []
        for seat_id in ALL_FACE_SEATS:
            attendee = attendees.get(seat_id)
            template = self.repo.get(attendee.person_id) if attendee and attendee.person_id else None
            items.append(
                FaceSeatAssignmentItem(
                    seatId=seat_id,
                    personId=attendee.person_id if attendee else None,
                    attendeeId=attendee.id if attendee else None,
                    personName=attendee.name if attendee else None,
                    templateRevision=template.revision if template else None,
                )
            )
        return FaceSeatAssignmentsResponse(
            meetingId=meeting.id,
            templateSetRevision=meeting.face_template_set_revision or 0,
            assignments=items,
        )

    def update_assignments(
        self,
        meeting_id: int,
        assignments: list[FaceSeatAssignmentUpdate],
    ) -> FaceSeatAssignmentsResponse:
        meeting = self.db.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError("Meeting not found", "MEETING_NOT_FOUND")
        if meeting.status == "finished":
            raise ValidationError(
                "Finished meeting assignments cannot be changed",
                "MEETING_FINISHED",
            )

        changed = False
        for item in assignments:
            current = self._assigned_attendee(meeting_id, item.seat_id)
            if current and current.person_id == item.person_id:
                continue
            if item.person_id is None:
                if current and current.checked_in:
                    raise ConflictError(
                        "A checked-in assignment cannot be removed",
                        "SEAT_ALREADY_CHECKED_IN",
                    )
                if current and meeting.status == "active":
                    self._require_vacant_seat(item.seat_id)
                if current:
                    current.assigned_seat_id = None
                    changed = True
                continue

            person = self.db.get(Person, item.person_id)
            if person is None or not person.active:
                raise NotFoundError("Person not found", "PERSON_NOT_FOUND")
            if item.seat_id in PARTICIPANT_SEATS and self.repo.get(item.person_id) is None:
                raise ValidationError(
                    f"Person {item.person_id} has no central face template",
                    "FACE_TEMPLATE_NOT_FOUND",
                )

            attendee = None
            if item.attendee_id is not None:
                attendee = self.db.get(Attendee, item.attendee_id)
                if attendee is None or attendee.meeting_id != meeting_id:
                    raise NotFoundError("Attendee not found", "ATTENDEE_NOT_FOUND")
                if attendee.person_id not in (None, item.person_id):
                    raise ConflictError(
                        "Attendee is linked to another stable person",
                        "ATTENDEE_PERSON_CONFLICT",
                    )
                attendee.person_id = item.person_id
            else:
                attendee = self.db.query(Attendee).filter(
                    Attendee.meeting_id == meeting_id,
                    Attendee.person_id == item.person_id,
                ).first()
            if attendee is None:
                attendee = Attendee(
                    meeting_id=meeting_id,
                    person_id=item.person_id,
                    name=person.name,
                    title="",
                )
                self.db.add(attendee)
                self.db.flush()
            if attendee.checked_in:
                raise ConflictError(
                    "A checked-in attendee cannot be reassigned",
                    "ATTENDEE_ALREADY_CHECKED_IN",
                )
            if meeting.status == "active":
                self._require_vacant_seat(item.seat_id)
                if attendee.assigned_seat_id not in (None, item.seat_id):
                    self._require_vacant_seat(attendee.assigned_seat_id)
            if attendee.assigned_seat_id not in (None, item.seat_id):
                attendee.assigned_seat_id = None
                self.db.flush()
            if current and current.id != attendee.id:
                if current.checked_in:
                    raise ConflictError(
                        "The target seat is checked in",
                        "SEAT_ALREADY_CHECKED_IN",
                    )
                current.assigned_seat_id = None
                self.db.flush()
            attendee.assigned_seat_id = item.seat_id
            changed = True

        if changed:
            meeting.face_template_set_revision = (
                (meeting.face_template_set_revision or 0) + 1
            )
            self.db.commit()
        return self.get_assignments(meeting_id)

    def seed_meeting_assignments(self, meeting: Meeting) -> None:
        previous = self.db.query(Meeting).filter(
            Meeting.status == "finished",
            Meeting.id != meeting.id,
        ).order_by(Meeting.ended_at.desc(), Meeting.created_at.desc()).first()
        selected: list[tuple[int, str]] = []
        if previous is not None:
            previous_attendees = self.db.query(Attendee).filter(
                Attendee.meeting_id == previous.id,
                Attendee.assigned_seat_id.in_(PARTICIPANT_SEATS),
                Attendee.person_id.is_not(None),
            ).order_by(Attendee.assigned_seat_id).all()
            selected = [
                (attendee.assigned_seat_id, attendee.person_id)
                for attendee in previous_attendees
                if self.repo.get(attendee.person_id) is not None
            ]
        if not selected:
            selected = [
                (seat_id, template.person_id)
                for seat_id, template in zip(PARTICIPANT_SEATS, self.repo.list_all())
            ]
        if not selected:
            return
        for seat_id, person_id in selected:
            person = self.db.get(Person, person_id)
            if person is None or not person.active:
                continue
            self.db.add(
                Attendee(
                    meeting_id=meeting.id,
                    person_id=person_id,
                    name=person.name,
                    title="",
                    assigned_seat_id=seat_id,
                )
            )
        meeting.face_template_set_revision = 1
        self.db.commit()

    def register_device_key(
        self,
        *,
        device_id: str,
        seat_id: int,
        token: str | None,
        public_key_pem: str,
    ) -> str:
        device = TabletDeviceService(self.db).authenticate(
            device_id=device_id,
            seat_id=seat_id,
            token=token,
        )
        try:
            key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
            if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
                raise ValueError("RSA-2048 or stronger is required")
            canonical = key.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except Exception as error:
            raise ValidationError(
                "Invalid tablet transport public key",
                "FACE_TRANSPORT_KEY_INVALID",
            ) from error
        fingerprint = hashlib.sha256(canonical).hexdigest()
        device.face_transport_public_key = public_key_pem
        device.face_transport_key_fingerprint = fingerprint
        self.db.commit()
        return fingerprint

    def build_active_bundle(
        self,
        *,
        device_id: str,
        seat_id: int,
        token: str | None,
    ) -> tuple[int, int, int, dict[str, str]]:
        if seat_id not in PARTICIPANT_SEATS:
            raise ValidationError(
                "Seat 1 does not consume participant template bundles",
                "FACE_TEMPLATE_SYNC_NOT_APPLICABLE",
            )
        device = TabletDeviceService(self.db).authenticate(
            device_id=device_id,
            seat_id=seat_id,
            token=token,
        )
        if not device.face_transport_public_key:
            raise ValidationError(
                "Tablet transport key is not registered",
                "FACE_TRANSPORT_KEY_REQUIRED",
            )
        meeting = self.db.query(Meeting).filter(Meeting.status == "active").first()
        if meeting is None:
            raise NotFoundError("No active meeting", "NO_ACTIVE_MEETING")
        attendee = self._assigned_attendee(meeting.id, seat_id)
        if attendee is None or attendee.person_id is None:
            raise ValidationError(
                "The participant seat has no assigned person",
                "SEAT_FACE_ASSIGNMENT_REQUIRED",
            )
        template = self.repo.get(attendee.person_id)
        if template is None:
            raise ValidationError(
                "The assigned person has no central face template",
                "FACE_TEMPLATE_SYNC_REQUIRED",
            )
        templates = [template]
        model_hash = template.model_hash
        policy = self.repo.get_policy(model_hash)
        if policy is None or policy.threshold_status != "PROVISIONAL":
            raise ValidationError(
                "The active face model has no approved provisional threshold",
                "FACE_THRESHOLD_REQUIRED",
            )
        try:
            decrypted_templates = [
                self.crypto.decrypt_at_rest(item.encrypted_payload)
                for item in templates
            ]
        except RuntimeError as error:
            raise ValidationError(
                "The central face-template encryption key is missing or invalid",
                "FACE_TEMPLATE_KEY_MISSING",
            ) from error
        except Exception as error:
            raise ValidationError(
                "The encrypted central face templates could not be read",
                "FACE_TEMPLATE_DECRYPT_FAILED",
            ) from error
        payload = {
            "meetingId": meeting.id,
            "templateSetRevision": meeting.face_template_set_revision or 0,
            "expectedPersonId": attendee.person_id,
            "modelVersion": template.model_version,
            "modelHash": model_hash,
            "pipelineVersion": template.pipeline_version,
            "embeddingDimension": template.embedding_dimension,
            "threshold": policy.threshold,
            "thresholdStatus": policy.threshold_status,
            "templates": decrypted_templates,
        }
        envelope = self.crypto.encrypt_for_device(
            payload,
            device.face_transport_public_key,
        )
        return meeting.id, meeting.face_template_set_revision or 0, len(templates), envelope

    def record_sync_ack(
        self,
        *,
        device_id: str,
        seat_id: int,
        token: str | None,
        meeting_id: int,
        revision: int,
        template_count: int,
        status: str,
        error: str | None,
    ) -> None:
        device = TabletDeviceService(self.db).authenticate(
            device_id=device_id,
            seat_id=seat_id,
            token=token,
        )
        device.face_template_meeting_id = meeting_id
        device.face_template_set_revision = revision
        device.face_template_sync_count = template_count
        device.face_template_sync_status = status
        device.face_template_sync_error = error
        self.db.commit()

    def _summary(self, template: FaceTemplate) -> FaceTemplateSummary:
        person = self.db.get(Person, template.person_id)
        return FaceTemplateSummary(
            personId=template.person_id,
            personName=person.name if person else template.person_id,
            modelVersion=template.model_version,
            modelHash=template.model_hash,
            pipelineVersion=template.pipeline_version,
            revision=template.revision,
            createdAt=template.created_at,
            updatedAt=template.updated_at,
        )

    def _protected_person_ids(self) -> set[str]:
        return {
            row[0]
            for row in self.db.query(Attendee.person_id).join(
                Meeting,
                Meeting.id == Attendee.meeting_id,
            ).filter(
                Meeting.status.in_(("pending", "active")),
                Attendee.assigned_seat_id.in_(PARTICIPANT_SEATS),
                Attendee.person_id.is_not(None),
            ).all()
        }

    def _bump_revisions_for_person(self, person_id: str) -> None:
        meetings = self.db.query(Meeting).join(
            Attendee,
            Attendee.meeting_id == Meeting.id,
        ).filter(
            Attendee.person_id == person_id,
            Meeting.status.in_(("pending", "active")),
        ).all()
        for meeting in meetings:
            meeting.face_template_set_revision = (
                (meeting.face_template_set_revision or 0) + 1
            )

    def _assigned_attendee(self, meeting_id: int, seat_id: int) -> Attendee | None:
        return self.db.query(Attendee).filter(
            Attendee.meeting_id == meeting_id,
            Attendee.assigned_seat_id == seat_id,
        ).first()

    def _require_vacant_seat(self, seat_id: int) -> None:
        seat = self.db.get(SeatState, seat_id)
        if seat is not None and seat.status != "vacant":
            raise ConflictError(
                "Active meeting seat changes require both seats to be vacant",
                "FACE_SEAT_NOT_VACANT",
            )

    @staticmethod
    def _validate_payload(payload: dict[str, Any], *, person_id: str) -> None:
        required = {
            "personId", "modelVersion", "modelHash", "pipelineVersion",
            "embeddingDimension", "normalSampleCount", "fillLightSampleCount",
            "normalEmbedding", "fillLightEmbedding", "threshold", "thresholdStatus",
        }
        if not required.issubset(payload):
            raise ValidationError(
                "Face template payload is incomplete",
                "FACE_TEMPLATE_INVALID",
            )
        if payload["personId"] != person_id:
            raise ValidationError(
                "Face template person does not match the URL",
                "FACE_TEMPLATE_PERSON_MISMATCH",
            )
        if int(payload["embeddingDimension"]) != 256:
            raise ValidationError("Face template must be 256-dimensional", "FACE_TEMPLATE_INVALID")
        for name in ("normalEmbedding", "fillLightEmbedding"):
            values = payload[name]
            if not isinstance(values, list) or len(values) != 256 or not all(
                isinstance(value, (int, float)) and math.isfinite(float(value))
                for value in values
            ):
                raise ValidationError("Face embedding is invalid", "FACE_TEMPLATE_INVALID")
        threshold = float(payload["threshold"])
        if not 0 <= threshold <= 1 or payload["thresholdStatus"] != "PROVISIONAL":
            raise ValidationError("Face threshold policy is invalid", "FACE_THRESHOLD_INVALID")
