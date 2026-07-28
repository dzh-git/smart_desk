"""Validate machine-readable SmartDesk integration and security contracts."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class ContractError(ValueError):
    pass


def load_object(relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"{relative_path}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{relative_path}: root must be a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_integration_config() -> None:
    config = load_object("config/smartdesk.integration.esp32.example.json")
    require(config.get("deploy_mode") == "esp32", "ESP32 example mode")
    require(config.get("seats_total") == 9, "ESP32 example seat count")
    require(
        config.get("arduino", {}).get("enabled") is False,
        "ESP32 example must not open central Arduino ports",
    )


def validate_android_config() -> None:
    config = load_object(
        "android_tablet/android-app/app/src/main/assets/"
        "device-config.example.json"
    )
    require(config.get("seatId") == 1, "Android example seatId")
    require(
        config.get("deviceId") == "tablet-seat-01",
        "Android example deviceId",
    )
    token = config.get("deviceToken")
    require(
        isinstance(token, str)
        and token.startswith("replace-")
        and len(token) >= 24,
        "Android example must contain a non-secret placeholder token",
    )
    for name in ("serverBaseUrl", "frontendBaseUrl"):
        value = config.get(name)
        require(
            isinstance(value, str)
            and value.startswith(("http://", "https://")),
            f"Android example {name}",
        )


def validate_model_contract() -> None:
    base = (
        "android_tablet/android-app/app/src/main/assets/models/"
    )
    config = load_object(base + "face_model_config.json")
    gate = load_object(base + "model-license-gate.json")
    require(
        config.get("modelVersion") == gate.get("modelVersion"),
        "Model version differs between config and license gate",
    )
    require(
        config.get("licenseLevel")
        == "NON_COMMERCIAL_RESEARCH_PROTOTYPE",
        "Current model must remain explicitly prototype-only",
    )
    require(
        gate.get("commercialDeploymentApproved") is False
        and gate.get("redistributionApproved") is False,
        "Current release approval must remain fail-closed",
    )


def validate_android_security_metadata() -> None:
    manifest = (
        ROOT
        / "android_tablet/android-app/app/src/main/AndroidManifest.xml"
    ).read_text(encoding="utf-8")
    backup = (
        ROOT
        / "android_tablet/android-app/app/src/main/res/xml/backup_rules.xml"
    ).read_text(encoding="utf-8")
    extraction = (
        ROOT
        / "android_tablet/android-app/app/src/main/res/xml/"
        "data_extraction_rules.xml"
    ).read_text(encoding="utf-8")
    require('android:allowBackup="false"' in manifest, "Android backup flag")
    require(
        'domain="sharedpref"' in backup
        and 'domain="sharedpref"' in extraction,
        "Android private preferences must be excluded from backup/transfer",
    )


def validate_no_tracked_face_weight() -> None:
    result = subprocess.run(
        ["git", "ls-files", "*.tflite"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0, "git ls-files failed")
    require(
        not result.stdout.strip(),
        "Face model binary must not be tracked before license approval",
    )


def validate_required_files() -> None:
    required = (
        ".github/workflows/software-verification.yml",
        "docs/integration/AUTONOMOUS_PROGRESS.md",
        "docs/integration/MODEL_LICENSE_GATE.md",
        "esp32_seat_controller/protocol.md",
        "new_coding_desk/docs/API_SPEC.md",
        "scripts/verify_all_software.ps1",
    )
    missing = [path for path in required if not (ROOT / path).is_file()]
    require(not missing, f"Missing required files: {', '.join(missing)}")


def validate_ci_entrypoints() -> None:
    workflow = (
        ROOT / ".github/workflows/software-verification.yml"
    ).read_text(encoding="utf-8")
    verification = (
        ROOT / "scripts/verify_all_software.ps1"
    ).read_text(encoding="utf-8")
    require(
        "./scripts/verify_all_software.ps1 -Profile CI" in workflow,
        "CI must call the repository one-command verification entrypoint",
    )
    for classification in (
        "REQUIRED",
        "OPTIONAL_ENVIRONMENT",
        "HARDWARE_REQUIRED",
    ):
        require(
            classification in verification,
            f"Verification script missing {classification} classification",
        )


def main() -> int:
    checks = (
        validate_required_files,
        validate_ci_entrypoints,
        validate_integration_config,
        validate_android_config,
        validate_model_contract,
        validate_android_security_metadata,
        validate_no_tracked_face_weight,
    )
    try:
        for check in checks:
            check()
    except (ContractError, OSError) as error:
        print(f"REPOSITORY_CONTRACT_INVALID: {error}", file=sys.stderr)
        return 1
    print(f"REPOSITORY_CONTRACTS_OK: {len(checks)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
