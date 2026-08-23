"""DTOs for host-managed face templates and tablet synchronization."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class EncryptedEnvelope(BaseModel):
    algorithm: str = "RSA-OAEP-256+A256GCM"
    encrypted_key: str = Field(alias="encryptedKey", min_length=16)
    nonce: str = Field(min_length=8)
    ciphertext: str = Field(min_length=16)

    model_config = {"populate_by_name": True}


class FaceTemplateUploadRequest(BaseModel):
    device_id: str = Field(alias="deviceId", min_length=3, max_length=64)
    envelope: EncryptedEnvelope

    model_config = {"populate_by_name": True}


class FaceTemplateSummary(BaseModel):
    person_id: str = Field(alias="personId")
    person_name: str = Field(alias="personName")
    model_version: str = Field(alias="modelVersion")
    model_hash: str = Field(alias="modelHash")
    pipeline_version: int = Field(alias="pipelineVersion")
    revision: int
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class FaceTemplateSaveResult(BaseModel):
    template: FaceTemplateSummary
    evicted_person_id: str | None = Field(None, alias="evictedPersonId")
    evicted_person_name: str | None = Field(None, alias="evictedPersonName")

    model_config = {"populate_by_name": True}


class FaceTemplateLibraryResponse(BaseModel):
    capacity: int = 81
    count: int
    templates: list[FaceTemplateSummary]


class FaceSeatAssignmentItem(BaseModel):
    seat_id: int = Field(alias="seatId", ge=1, le=9)
    person_id: str | None = Field(None, alias="personId")
    attendee_id: int | None = Field(None, alias="attendeeId")
    person_name: str | None = Field(None, alias="personName")
    template_revision: int | None = Field(None, alias="templateRevision")

    model_config = {"populate_by_name": True}


class FaceSeatAssignmentUpdate(BaseModel):
    seat_id: int = Field(alias="seatId", ge=1, le=9)
    person_id: str | None = Field(None, alias="personId")
    attendee_id: int | None = Field(None, alias="attendeeId")

    model_config = {"populate_by_name": True}


class FaceSeatAssignmentsRequest(BaseModel):
    device_id: str = Field(alias="deviceId", min_length=3, max_length=64)
    assignments: list[FaceSeatAssignmentUpdate] = Field(max_length=9)

    @field_validator("assignments")
    @classmethod
    def unique_seats(cls, value: list[FaceSeatAssignmentUpdate]):
        seats = [item.seat_id for item in value]
        if len(seats) != len(set(seats)):
            raise ValueError("seat assignments must be unique")
        people = [item.person_id for item in value if item.person_id]
        if len(people) != len(set(people)):
            raise ValueError("one person cannot be assigned to multiple seats")
        return value

    model_config = {"populate_by_name": True}


class FaceSeatAssignmentsResponse(BaseModel):
    meeting_id: int = Field(alias="meetingId")
    template_set_revision: int = Field(alias="templateSetRevision")
    assignments: list[FaceSeatAssignmentItem]

    model_config = {"populate_by_name": True}


class FaceTransportKeyRequest(BaseModel):
    seat_id: int = Field(alias="seatId", ge=1, le=9)
    public_key_pem: str = Field(alias="publicKeyPem", min_length=100, max_length=4096)

    model_config = {"populate_by_name": True}


class FaceTemplateSyncAckRequest(BaseModel):
    seat_id: int = Field(alias="seatId", ge=2, le=9)
    meeting_id: int = Field(alias="meetingId", gt=0)
    template_set_revision: int = Field(alias="templateSetRevision", ge=0)
    template_count: int = Field(alias="templateCount", ge=0, le=9)
    status: str = Field(pattern=r"^(SYNCED|ERROR)$")
    error: str | None = Field(None, max_length=300)

    model_config = {"populate_by_name": True}


class FaceTemplateBundleResponse(BaseModel):
    meeting_id: int = Field(alias="meetingId")
    template_set_revision: int = Field(alias="templateSetRevision")
    template_count: int = Field(alias="templateCount")
    envelope: EncryptedEnvelope

    model_config = {"populate_by_name": True}


class ServerTransportKeyResponse(BaseModel):
    algorithm: str = "RSA-OAEP-256+A256GCM"
    public_key_pem: str = Field(alias="publicKeyPem")

    model_config = {"populate_by_name": True}
