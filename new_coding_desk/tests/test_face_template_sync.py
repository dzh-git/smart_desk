"""Central face-template encryption, authorization, and sync contracts."""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.exceptions import ValidationError
from backend.models.attendee import Attendee
from backend.models.face_template import FaceTemplate
from backend.models.meeting import Meeting
from backend.models.person import Person
from backend.schemas.face_template import FaceSeatAssignmentUpdate
from backend.security.face_template_crypto import AAD, AT_REST_KEY_FILE, FaceTemplateCrypto
from backend.services.face_template_service import FaceTemplateService
from backend.services.tablet_device_service import TabletDeviceService

TOKEN = "test-device-secret-token-000001"
MODEL_HASH = "a" * 64


def _payload(person_id: str) -> dict:
    embedding = [float(index) / 256 for index in range(256)]
    return {
        "personId": person_id,
        "modelVersion": "mobilefacenet-test",
        "modelHash": MODEL_HASH,
        "pipelineVersion": 3,
        "embeddingDimension": 256,
        "normalSampleCount": 5,
        "fillLightSampleCount": 5,
        "normalEmbedding": embedding,
        "fillLightEmbedding": embedding,
        "threshold": 0.55,
        "thresholdStatus": "PROVISIONAL",
    }


def _upload_envelope(crypto: FaceTemplateCrypto, payload: dict) -> dict[str, str]:
    public_key = serialization.load_pem_public_key(
        crypto.server_public_key_pem().encode("ascii")
    )
    key = os.urandom(32)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(
        nonce,
        json.dumps(payload, separators=(",", ":")).encode(),
        AAD,
    )
    encrypted_key = public_key.encrypt(
        key,
        padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return {
        "algorithm": "RSA-OAEP-256+A256GCM",
        "encryptedKey": base64.b64encode(encrypted_key).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def _save(service: FaceTemplateService, db, person_id: str, name: str):
    db.add(Person(id=person_id, name=name, active=True))
    db.commit()
    return service.save_encrypted_upload(
        person_id=person_id,
        envelope=_upload_envelope(service.crypto, _payload(person_id)),
    )


def test_only_bound_seat_one_can_manage_templates(db, tmp_path):
    TabletDeviceService(db).provision(
        device_id="participant-tablet",
        seat_id=2,
        token=TOKEN,
    )
    service = FaceTemplateService(db, FaceTemplateCrypto(tmp_path))

    with pytest.raises(ValidationError) as caught:
        service.authenticate_host(device_id="participant-tablet", token=TOKEN)

    assert caught.value.error_code == "HOST_DEVICE_REQUIRED"


def test_templates_are_encrypted_at_rest_and_missing_key_fails_closed(db, tmp_path):
    service = FaceTemplateService(db, FaceTemplateCrypto(tmp_path))
    _save(service, db, "person-001", "测试人员一")
    stored = db.get(FaceTemplate, "person-001")

    assert stored is not None
    assert "normalEmbedding" not in stored.encrypted_payload
    (tmp_path / AT_REST_KEY_FILE).unlink()
    db.add(Person(id="person-002", name="测试人员二", active=True))
    db.commit()

    with pytest.raises(ValidationError) as caught:
        service.save_encrypted_upload(
            person_id="person-002",
            envelope=_upload_envelope(service.crypto, _payload("person-002")),
        )

    assert caught.value.error_code == "FACE_TEMPLATE_KEY_MISSING"


def test_participant_bundle_is_device_encrypted_and_contains_only_assigned_person(db, tmp_path):
    service = FaceTemplateService(db, FaceTemplateCrypto(tmp_path))
    _save(service, db, "person-001", "测试人员一")
    _save(service, db, "person-002", "测试人员二")
    meeting = Meeting(title="同步测试", status="active", face_template_set_revision=4)
    db.add(meeting)
    db.flush()
    db.add_all([
        Attendee(meeting_id=meeting.id, person_id="person-001", name="测试人员一", assigned_seat_id=2),
        Attendee(meeting_id=meeting.id, person_id="person-002", name="测试人员二", assigned_seat_id=3),
    ])
    TabletDeviceService(db).provision(
        device_id="participant-tablet",
        seat_id=2,
        token=TOKEN,
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    service.register_device_key(
        device_id="participant-tablet",
        seat_id=2,
        token=TOKEN,
        public_key_pem=public_pem,
    )

    meeting_id, revision, count, envelope = service.build_active_bundle(
        device_id="participant-tablet",
        seat_id=2,
        token=TOKEN,
    )
    aes_key = private_key.decrypt(
        base64.b64decode(envelope["encryptedKey"]),
        padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    plaintext = AESGCM(aes_key).decrypt(
        base64.b64decode(envelope["nonce"]),
        base64.b64decode(envelope["ciphertext"]),
        AAD,
    )
    payload = json.loads(plaintext)

    assert (meeting_id, revision, count) == (meeting.id, 4, 1)
    assert payload["expectedPersonId"] == "person-001"
    assert [item["personId"] for item in payload["templates"]] == ["person-001"]
    assert payload["threshold"] == pytest.approx(0.55)


def test_host_assignment_accepts_local_person_without_central_template(db, tmp_path):
    service = FaceTemplateService(db, FaceTemplateCrypto(tmp_path))
    _save(service, db, "person-002", "参会者")
    db.add(Person(id="host-001", name="主持人", active=True))
    meeting = Meeting(title="主持人分配", status="pending")
    db.add(meeting)
    db.commit()

    result = service.update_assignments(
        meeting.id,
        [
            FaceSeatAssignmentUpdate(seatId=1, personId="host-001"),
            FaceSeatAssignmentUpdate(seatId=2, personId="person-002"),
        ],
    )

    assignments = {item.seat_id: item for item in result.assignments}
    assert len(assignments) == 9
    assert assignments[1].person_id == "host-001"
    assert assignments[1].template_revision is None
    assert assignments[2].person_id == "person-002"
    assert assignments[2].template_revision == 1


def test_capacity_evicts_oldest_template_not_used_by_open_meeting(db, tmp_path):
    crypto = FaceTemplateCrypto(tmp_path)
    service = FaceTemplateService(db, crypto)
    encrypted = crypto.encrypt_at_rest(_payload("placeholder"))
    origin = datetime(2025, 1, 1)
    people = [
        Person(id=f"person-{index:03d}", name=f"人员{index:03d}", active=True)
        for index in range(1, 83)
    ]
    db.add_all(people)
    db.flush()
    db.add_all([
        FaceTemplate(
            person_id=f"person-{index:03d}",
            model_version="mobilefacenet-test",
            model_hash=MODEL_HASH,
            pipeline_version=3,
            embedding_dimension=256,
            normal_sample_count=5,
            fill_light_sample_count=5,
            encrypted_payload=encrypted,
            revision=1,
            created_at=origin + timedelta(minutes=index),
            updated_at=origin + timedelta(minutes=index),
        )
        for index in range(1, 82)
    ])
    meeting = Meeting(title="受保护会议", status="pending")
    db.add(meeting)
    db.flush()
    db.add(Attendee(
        meeting_id=meeting.id,
        person_id="person-001",
        name="人员001",
        assigned_seat_id=2,
    ))
    db.commit()

    result = service.save_encrypted_upload(
        person_id="person-082",
        envelope=_upload_envelope(crypto, _payload("person-082")),
    )

    assert result.evicted_person_id == "person-002"
    assert db.get(FaceTemplate, "person-001") is not None
    assert db.get(FaceTemplate, "person-002") is None
    assert db.get(FaceTemplate, "person-082") is not None
