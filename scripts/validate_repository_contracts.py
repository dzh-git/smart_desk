"""Validate machine-readable SmartDesk integration and security contracts."""
from __future__ import annotations

import json
import re
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
    arduino = load_object(
        "config/smartdesk.integration.arduino.example.json"
    )
    require(arduino.get("deploy_mode") == "central", "Arduino bench mode")
    require(
        arduino.get("arduino", {}).get("seats", {}).get("1")
        == "COM_REPLACE_ME",
        "Arduino example must not contain a machine COM port",
    )


def validate_android_config() -> None:
    legacy_config = (
        ROOT
        / "android_tablet/android-app/app/src/main/assets/"
        "device-config.example.json"
    )
    require(
        not legacy_config.exists(),
        "Android must not package a manually editable device config",
    )
    bridge = (
        ROOT
        / "android_tablet/android-app/app/src/main/java/com/smartdesk/"
        "tablet/bridge/AndroidBridge.kt"
    ).read_text(encoding="utf-8")
    require(
        "provisionDeviceConfig" in bridge
        and "saveDeviceConfig" not in bridge,
        "Android Bridge must provision through the central host",
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
        "android.intent.category.HOME" in manifest
        and "android.intent.category.DEFAULT" in manifest
        and 'android:launchMode="singleTask"' in manifest,
        "Android tablet must launch as a single-task HOME activity",
    )
    require(
        "android.permission.RECEIVE_BOOT_COMPLETED" not in manifest
        and "android.intent.action.BOOT_COMPLETED" not in manifest,
        "Android HOME launcher must not use a boot-start receiver",
    )
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
        "README.md",
        "docs/integration/ANDROID_BRIDGE_CONTRACT.md",
        "docs/integration/ARCHITECTURE.md",
        "docs/integration/COMPATIBILITY.md",
        "docs/integration/ESP32_PROTOCOL.md",
        "docs/integration/FIELD_VALIDATION_QUICKSTART.md",
        "docs/integration/HUMAN_VALIDATION_REQUIRED.md",
        "docs/integration/IDENTITY_CHECKIN_CONTRACT.md",
        "docs/integration/MODEL_LICENSE_GATE.md",
        "docs/integration/NINE_SEAT_DEPLOYMENT.md",
        "docs/integration/ONE_SEAT_RUNBOOK.md",
        "docs/integration/RELEASE_READINESS.md",
        "esp32_seat_controller/protocol.md",
        "new_coding_desk/docs/API_SPEC.md",
        "deployment/portable/README.md",
        "RUN_VALIDATION.bat",
        "SETUP_PYTHON.bat",
        "PIO.bat",
        ".python-version",
        "scripts/check_python_runtime.py",
        "scripts/setup_python.ps1",
        "scripts/verify_all_software.ps1",
    )
    missing = [path for path in required if not (ROOT / path).is_file()]
    require(not missing, f"Missing required files: {', '.join(missing)}")


def validate_markdown_links() -> None:
    documents = [
        ROOT / "README.md",
        ROOT / "DOCUMENTATION_INDEX.md",
        *(ROOT / "docs/integration").glob("*.md"),
    ]
    errors: list[str] = []
    link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    uri_pattern = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for raw_target in link_pattern.findall(text):
            target = raw_target.strip().strip("<>")
            if (
                not target
                or target.startswith(("#", "//"))
                or uri_pattern.match(target)
            ):
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                errors.append(
                    f"{document.relative_to(ROOT)} -> {raw_target}"
                )
    require(
        not errors,
        "Broken local Markdown links: " + ", ".join(errors),
    )


def validate_integration_document_contracts() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in (
        "## 架构与边界",
        "## 目录",
        "## 环境",
        "## 中央主机启动",
        "## Android",
        "## ESP32",
        "## 自动验证",
    ):
        require(heading in readme, f"Root README missing {heading}")

    human = (
        ROOT / "docs/integration/HUMAN_VALIDATION_REQUIRED.md"
    ).read_text(encoding="utf-8")
    for number in range(1, 16):
        identifier = f"HV-{number:02d}"
        require(
            f"## {identifier} " in human,
            f"Human validation missing {identifier}",
        )
        require(
            f"| {identifier} |" in human,
            f"Human validation record table missing {identifier}",
        )
    for field in (
        "准备条件",
        "操作步骤",
        "预期结果",
        "失败表现",
        "保存日志",
        "结果 PASS/FAIL",
    ):
        require(field in human, f"Human validation missing {field}")

    esp32_entry = (
        ROOT / "docs/integration/ESP32_PROTOCOL.md"
    ).read_text(encoding="utf-8")
    require(
        "唯一权威来源" in esp32_entry
        and "../../esp32_seat_controller/protocol.md" in esp32_entry,
        "ESP32 integration doc must point to the canonical protocol",
    )

    release = (
        ROOT / "docs/integration/RELEASE_READINESS.md"
    ).read_text(encoding="utf-8")
    require(
        "HARDWARE_VALIDATION_REQUIRED" in release
        and "MODEL_LICENSE_GATE_BLOCKED" in release,
        "Release report must preserve hardware and model-license gates",
    )


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


def validate_python_environment_contract() -> None:
    version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    require(version == "3.11", "SmartDesk Python version must be 3.11")

    gate = (ROOT / "scripts/check_python_runtime.py").read_text(
        encoding="utf-8"
    )
    setup = (ROOT / "scripts/setup_python.ps1").read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github/workflows/software-verification.yml"
    ).read_text(encoding="utf-8")
    launcher = (ROOT / "new_coding_desk/start.bat").read_text(
        encoding="utf-8"
    )
    verification = (ROOT / "scripts/verify_all_software.ps1").read_text(
        encoding="utf-8"
    )
    require(
        "REQUIRED_VERSION = (3, 11)" in gate,
        "Python runtime gate must require 3.11",
    )
    require(
        'Join-Path $repoRoot ".venv"' in setup
        and '$env:PYTHONUTF8 = "1"' in setup
        and '".tools\\platformio-venv"' in setup,
        "Python setup must create the UTF-8 repository environment",
    )
    require(
        'python-version: "3.11"' in workflow
        and ".\\.venv\\Scripts\\python.exe" in workflow,
        "CI must use Python 3.11 through the repository environment",
    )
    for name, content in (
        ("central launcher", launcher),
        ("verification", verification),
    ):
        require(
            ".venv\\Scripts\\python.exe" in content
            and "check_python_runtime.py" in content,
            f"{name} must use the repository Python gate",
        )

    for script in (ROOT / "smartdesk_gesture_controller").glob("start*.bat"):
        content = script.read_text(encoding="utf-8")
        require(
            "REPO_ROOT%\\.venv\\Scripts\\python.exe" in content
            and "check_python_runtime.py" in content,
            f"{script.name} must use the repository Python gate",
        )


def main() -> int:
    checks = (
        validate_required_files,
        validate_markdown_links,
        validate_integration_document_contracts,
        validate_ci_entrypoints,
        validate_python_environment_contract,
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
