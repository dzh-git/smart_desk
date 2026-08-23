"""Envelope encryption for centrally managed biometric templates."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AAD = b"smartdesk-face-template-v1"
AT_REST_KEY_FILE = "face-template-master.key"
SERVER_PRIVATE_KEY_FILE = "face-template-server-private.pem"


def _default_key_dir() -> Path:
    configured = os.environ.get("SMARTDESK_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / ".smartdesk-runtime"


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


class FaceTemplateCrypto:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or _default_key_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _load_at_rest_key(self, *, create: bool) -> bytes:
        path = self.data_dir / AT_REST_KEY_FILE
        if path.exists():
            key = path.read_bytes()
            if len(key) != 32:
                raise RuntimeError("FACE_TEMPLATE_KEY_INVALID")
            return key
        if not create:
            raise RuntimeError("FACE_TEMPLATE_KEY_MISSING")
        key = os.urandom(32)
        path.write_bytes(key)
        return key

    def require_at_rest_key(self) -> None:
        self._load_at_rest_key(create=False)

    def _load_or_create_server_private_key(self):
        path = self.data_dir / SERVER_PRIVATE_KEY_FILE
        if path.exists():
            return serialization.load_pem_private_key(
                path.read_bytes(),
                password=None,
            )
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        path.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        return private_key

    def server_public_key_pem(self) -> str:
        return self._load_or_create_server_private_key().public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def encrypt_at_rest(self, payload: dict[str, Any]) -> str:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._load_at_rest_key(create=True)).encrypt(
            nonce,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            AAD,
        )
        return json.dumps(
            {"version": 1, "nonce": _b64(nonce), "ciphertext": _b64(ciphertext)},
            separators=(",", ":"),
        )

    def decrypt_at_rest(self, encoded: str) -> dict[str, Any]:
        raw = json.loads(encoded)
        plaintext = AESGCM(self._load_at_rest_key(create=False)).decrypt(
            _unb64(raw["nonce"]),
            _unb64(raw["ciphertext"]),
            AAD,
        )
        return json.loads(plaintext.decode("utf-8"))

    def decrypt_upload_envelope(self, envelope: dict[str, str]) -> dict[str, Any]:
        if envelope.get("algorithm") != "RSA-OAEP-256+A256GCM":
            raise ValueError("FACE_TEMPLATE_ENVELOPE_ALGORITHM_INVALID")
        private_key = self._load_or_create_server_private_key()
        aes_key = private_key.decrypt(
            _unb64(envelope["encryptedKey"]),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        plaintext = AESGCM(aes_key).decrypt(
            _unb64(envelope["nonce"]),
            _unb64(envelope["ciphertext"]),
            AAD,
        )
        return json.loads(plaintext.decode("utf-8"))

    def encrypt_for_device(
        self,
        payload: dict[str, Any],
        public_key_pem: str,
    ) -> dict[str, str]:
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode("ascii")
        )
        aes_key = os.urandom(32)
        nonce = os.urandom(12)
        ciphertext = AESGCM(aes_key).encrypt(
            nonce,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            AAD,
        )
        encrypted_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return {
            "algorithm": "RSA-OAEP-256+A256GCM",
            "encryptedKey": _b64(encrypted_key),
            "nonce": _b64(nonce),
            "ciphertext": _b64(ciphertext),
        }
