"""Machine-verifiable release gate for the Android face model.

Prototype verification succeeds only while the repository honestly records
the current model as non-commercial and release-blocked. Release verification
requires explicit commercial/redistribution approval plus a matching local
model hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = (
    ROOT
    / "android_tablet"
    / "android-app"
    / "app"
    / "src"
    / "main"
    / "assets"
    / "models"
)
CONFIG_PATH = MODEL_DIR / "face_model_config.json"
GATE_PATH = MODEL_DIR / "model-license-gate.json"
MODEL_CARD_PATH = MODEL_DIR / "MODEL_CARD.md"


class GateError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"invalid or missing {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise GateError(f"{path.name} must contain a JSON object")
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError(f"{field} must be a non-empty string")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_prototype_state(
    config: dict[str, Any],
    gate: dict[str, Any],
    model_card: str,
) -> None:
    if gate.get("schemaVersion") != 1:
        raise GateError("unsupported model license gate schema")
    if gate.get("modelVersion") != config.get("modelVersion"):
        raise GateError("modelVersion differs between gate and model config")
    if gate.get("weightLicense") != "NON_COMMERCIAL_RESEARCH_ONLY":
        raise GateError("prototype weightLicense must remain explicit")
    if gate.get("commercialDeploymentApproved") is not False:
        raise GateError("prototype must not claim commercial approval")
    if gate.get("redistributionApproved") is not False:
        raise GateError("prototype must not claim redistribution approval")
    if gate.get("approvalRecord") is not None:
        raise GateError("prototype must not contain a false approval record")
    if config.get("licenseLevel") != "NON_COMMERCIAL_RESEARCH_PROTOTYPE":
        raise GateError("model config does not expose prototype license level")
    required_phrases = (
        "non-commercial research",
        "Commercial deployment: prohibited",
    )
    if any(phrase not in model_card for phrase in required_phrases):
        raise GateError("MODEL_CARD.md does not state the license boundary")


def verify_release_state(
    config: dict[str, Any],
    gate: dict[str, Any],
) -> None:
    if gate.get("schemaVersion") != 1:
        raise GateError("unsupported model license gate schema")
    if gate.get("modelVersion") != config.get("modelVersion"):
        raise GateError("modelVersion differs between gate and model config")
    if gate.get("weightLicense") != "COMMERCIAL_APPROVED":
        raise GateError("weight license is not commercially approved")
    if gate.get("commercialDeploymentApproved") is not True:
        raise GateError("commercial deployment approval is absent")
    if gate.get("redistributionApproved") is not True:
        raise GateError("redistribution approval is absent")
    if config.get("licenseLevel") != "COMMERCIAL_APPROVED":
        raise GateError("model config licenseLevel is not release-approved")
    approval = gate.get("approvalRecord")
    if not isinstance(approval, dict):
        raise GateError("approvalRecord is absent")
    for field in ("reviewer", "approvedAt", "evidence"):
        _require_text(approval.get(field), f"approvalRecord.{field}")

    asset_name = _require_text(config.get("assetFile"), "assetFile")
    model_path = MODEL_DIR.parent / asset_name
    if not model_path.is_file():
        raise GateError(f"approved model asset is missing: {model_path}")
    expected_hash = _require_text(config.get("modelSha256"), "modelSha256")
    actual_hash = _sha256(model_path)
    if actual_hash.lower() != expected_hash.lower():
        raise GateError("approved model asset SHA-256 does not match config")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("prototype", "release"),
        required=True,
    )
    args = parser.parse_args()
    try:
        config = _load_json(CONFIG_PATH)
        gate = _load_json(GATE_PATH)
        model_card = MODEL_CARD_PATH.read_text(encoding="utf-8")
        if args.mode == "prototype":
            verify_prototype_state(config, gate, model_card)
            print(
                "MODEL_LICENSE_GATE_PROTOTYPE_OK: release remains blocked"
            )
        else:
            verify_release_state(config, gate)
            print("MODEL_LICENSE_GATE_RELEASE_OK")
    except (GateError, OSError) as error:
        print(
            f"MODEL_LICENSE_GATE_BLOCKED: {error}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
