from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "manage_android_tablet.ps1"
LEGACY_VERIFY_SCRIPT = ROOT / "scripts" / "verify_android_device.ps1"


def _pwsh() -> str:
    executable = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required for tablet fleet script tests")
    return executable


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _pwsh(),
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            *args,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _fake_adb(tmp_path: Path) -> tuple[Path, Path]:
    log_path = tmp_path / "adb-commands.log"
    script_path = tmp_path / "fake-adb.ps1"
    script_path.write_text(
        f"""
$commandLine = $args -join " "
Add-Content -LiteralPath '{log_path}' -Value $commandLine -Encoding UTF8
if ($commandLine -eq "devices") {{
    Write-Output "List of devices attached"
    Write-Output "FAKE-SERIAL device"
    exit 0
}}
if ($commandLine -match "install -r") {{
    Write-Output "Success"
    exit 0
}}
if ($commandLine -match "dumpsys package") {{
    Write-Output "versionName=0.9.0"
    Write-Output "android.permission.CAMERA: granted=true"
    Write-Output "android.permission.RECORD_AUDIO: granted=true"
    exit 0
}}
if ($commandLine -match "resolve-activity") {{
    Write-Output "com.smartdesk.tablet/.MainActivity"
    exit 0
}}
if ($commandLine -match "settings get global stay_on_while_plugged_in") {{
    Write-Output "7"
    exit 0
}}
if ($commandLine -match "locksettings get-disabled") {{
    Write-Output "true"
    exit 0
}}
if ($commandLine -match "dumpsys deviceidle whitelist") {{
    Write-Output "system,com.smartdesk.tablet,10001"
    exit 0
}}
if ($commandLine -match "cmd wifi status") {{
    Write-Output "Wifi is enabled"
    Write-Output "connected to DZH 2053"
    exit 0
}}
if ($commandLine -match "dumpsys activity activities") {{
    Write-Output "mResumedActivity: com.smartdesk.tablet/.MainActivity"
    exit 0
}}
if ($commandLine -match "logcat -d") {{
    Write-Output "WebView loaded: http://192.168.137.1:5173/seat/2"
    Write-Output "deviceToken=secret-value-must-not-leak"
    Write-Output "Authorization: Bearer secret-auth-value-must-not-leak"
    Write-Output "maintenancePin=654321"
    exit 0
}}
Write-Output "OK"
exit 0
""".strip(),
        encoding="utf-8",
    )
    return script_path, log_path


def test_configure_is_dry_run_until_apply_is_explicit() -> None:
    result = _run(
        "-Action",
        "Configure",
        "-SeatId",
        "2",
        "-SkipInstall",
        "-AdbPath",
        "Z:/missing/adb.exe",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "DRY RUN" in result.stdout
    assert "Seat 2" in result.stdout
    assert "CAMERA" in result.stdout
    assert "RECORD_AUDIO" in result.stdout
    assert "default HOME" in result.stdout


def test_apply_configures_permissions_home_power_and_lock_policy(
    tmp_path: Path,
) -> None:
    adb_path, log_path = _fake_adb(tmp_path)

    result = _run(
        "-Action",
        "Configure",
        "-SeatId",
        "2",
        "-SkipInstall",
        "-Apply",
        "-AdbPath",
        str(adb_path),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    commands = log_path.read_text(encoding="utf-8")
    assert "pm grant com.smartdesk.tablet android.permission.CAMERA" in commands
    assert (
        "pm grant com.smartdesk.tablet android.permission.RECORD_AUDIO"
        in commands
    )
    assert (
        "cmd package set-home-activity "
        "com.smartdesk.tablet/.MainActivity" in commands
    )
    assert "settings put global stay_on_while_plugged_in 7" in commands
    assert "locksettings set-disabled true" in commands
    assert "deviceidle whitelist +com.smartdesk.tablet" in commands
    assert "am start -n com.smartdesk.tablet/.MainActivity" in commands


def test_verify_reads_version_from_gradle_and_redacts_report(
    tmp_path: Path,
) -> None:
    adb_path, _ = _fake_adb(tmp_path)
    report_path = tmp_path / "seat-02.json"

    result = _run(
        "-Action",
        "Verify",
        "-SeatId",
        "2",
        "-ExpectedWifiSsid",
        "DZH 2053",
        "-AdbPath",
        str(adb_path),
        "-ReportPath",
        str(report_path),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["seatId"] == 2
    assert report["expectedVersion"] == "0.9.0"
    assert all(item["status"] == "PASS" for item in report["results"])
    assert "secret-value-must-not-leak" not in report_text
    assert "secret-auth-value-must-not-leak" not in report_text
    assert "654321" not in report_text
    assert "[REDACTED]" in report_text


def test_seat_id_outside_nine_seat_range_is_rejected() -> None:
    result = _run("-Action", "Audit", "-SeatId", "10")

    assert result.returncode != 0
    assert "10" in result.stderr


def test_legacy_verifier_uses_current_android_build_version(
    tmp_path: Path,
) -> None:
    adb_script, _ = _fake_adb(tmp_path)
    adb_cmd = tmp_path / "adb.cmd"
    adb_cmd.write_text(
        (
            "@echo off\n"
            f'pwsh.exe -NoLogo -NoProfile -File "{adb_script}" %*\n'
            "exit /b %ERRORLEVEL%\n"
        ),
        encoding="utf-8",
    )
    apk_path = (
        ROOT
        / "android_tablet"
        / "android-app"
        / "app"
        / "build"
        / "outputs"
        / "apk"
        / "debug"
        / "app-debug.apk"
    )
    if not apk_path.is_file():
        pytest.skip("Android debug APK is required for legacy verifier test")
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]

    result = subprocess.run(
        [
            _pwsh(),
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(LEGACY_VERIFY_SCRIPT),
            "-ApkPath",
            str(apk_path.relative_to(ROOT)),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Expected versionName 0.9.0" in result.stdout
