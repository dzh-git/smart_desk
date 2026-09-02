from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "new_coding_desk" / "frontend"


def test_speech_e2e_command_collects_only_speech_specs() -> None:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        pytest.skip("npm is required for the speech E2E command contract")

    result = subprocess.run(
        [npm, "run", "e2e:speech", "--", "--list", "--reporter=json"],
        cwd=FRONTEND,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_start = result.stdout.find("{")
    assert report_start >= 0, result.stdout
    report = json.loads(result.stdout[report_start:])
    files = {
        spec["file"]
        for suite in report["suites"]
        for child in suite.get("suites", [])
        for spec in child.get("specs", [])
    }
    assert files == {
        "deterministic-caption.spec.ts",
        "speech-consistency.spec.ts",
    }
    collected = sum(
        len(spec.get("tests", []))
        for suite in report["suites"]
        for child in suite.get("suites", [])
        for spec in child.get("specs", [])
    )
    assert collected == 3
