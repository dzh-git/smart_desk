"""Static contract checks for the portable internal-demo package."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "deployment" / "portable"
PACKAGE = PORTABLE / "package"


def main() -> int:
    required = [
        PORTABLE / "build-portable.ps1",
        PACKAGE / "INSTALL.bat",
        PACKAGE / "START.bat",
        PACKAGE / "DOCTOR.bat",
        PACKAGE / "UNINSTALL.bat",
        PACKAGE / "INTERNAL_DEMO.txt",
        PACKAGE / "scripts" / "INSTALL.ps1",
        PACKAGE / "scripts" / "START.ps1",
        PACKAGE / "scripts" / "DOCTOR.ps1",
        PACKAGE / "scripts" / "UNINSTALL.ps1",
        ROOT / "new_coding_desk" / "frontend_server.py",
        ROOT / "new_coding_desk" / "migrate_database.py",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert not missing, f"missing portable package files: {missing}"

    start = (PACKAGE / "scripts" / "START.ps1").read_text(encoding="utf-8")
    install = (PACKAGE / "scripts" / "INSTALL.ps1").read_text(encoding="utf-8")
    build = (PORTABLE / "build-portable.ps1").read_text(encoding="utf-8")
    assert "frontend_server:app" in start
    assert "http://127.0.0.1:8000/api/health" in start
    assert "http://127.0.0.1:8000/health" not in start
    assert "npm run dev" not in start
    for variable in (
        "SMARTDESK_CONFIG_PATH",
        "SMARTDESK_DATA_DIR",
        "SMARTDESK_ESP32_DEVICE_TOKENS_FILE",
    ):
        assert variable in start
    assert "RandomNumberGenerator" in install
    assert "CALIBRATION_PENDING" in (
        PACKAGE / "INTERNAL_DEMO.txt"
    ).read_text(encoding="utf-8")
    assert "SpeechModelsDirectory" in build
    assert "GestureModelsDirectory" in build
    for model_extension in (
        '".tflite"',
        '".task"',
        '".onnx"',
        '".pt"',
        '".pth"',
        '".ckpt"',
    ):
        assert model_extension in build
    print(json.dumps({"status": "PASS", "channel": "INTERNAL_DEMO"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
