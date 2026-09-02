from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "deployment" / "tablet" / "build-tablet-deploy.ps1"


def _pwsh() -> str:
    executable = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required for tablet package tests")
    return executable


def _windows_powershell() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if executable is None:
        pytest.skip("Windows PowerShell is required for package compatibility")
    return executable


def test_builder_produces_self_contained_tablet_deploy_package(
    tmp_path: Path,
) -> None:
    platform_tools = tmp_path / "platform-tools"
    platform_tools.mkdir()
    for name in (
        "adb.exe",
        "AdbWinApi.dll",
        "AdbWinUsbApi.dll",
        "NOTICE.txt",
    ):
        (platform_tools / name).write_bytes(f"fake-{name}".encode("ascii"))
    apk = tmp_path / "SmartDeskTablet.apk"
    apk.write_bytes(b"fake-apk-for-package-contract")
    output = ROOT / "artifacts" / f"tablet-package-test-{uuid.uuid4().hex}"

    try:
        result = subprocess.run(
            [
                _pwsh(),
                "-NoLogo",
                "-NoProfile",
                "-File",
                str(BUILD_SCRIPT),
                "-OutputDirectory",
                str(output),
                "-PlatformToolsDirectory",
                str(platform_tools),
                "-ApkPath",
                str(apk),
                "-SkipBuild",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        required = (
            "DEPLOY_TABLET.bat",
            "QUICK_START.txt",
            "package-manifest.json",
            "payload/SmartDeskTablet.apk",
            "platform-tools/adb.exe",
            "platform-tools/AdbWinApi.dll",
            "platform-tools/AdbWinUsbApi.dll",
            "platform-tools/NOTICE.txt",
            "scripts/DEPLOY_TABLET.ps1",
            "scripts/manage_android_tablet.ps1",
        )
        for relative in required:
            assert (output / relative).is_file(), relative

        manifest = json.loads(
            (output / "package-manifest.json").read_text(encoding="utf-8-sig")
        )
        assert manifest["product"] == "SmartDesk Tablet Deploy"
        assert manifest["platformToolsBundled"] is True
        assert len(manifest["apkSha256"]) == 64

        dry_run = subprocess.run(
            [
                _pwsh(),
                "-NoLogo",
                "-NoProfile",
                "-File",
                str(output / "scripts" / "DEPLOY_TABLET.ps1"),
                "-SeatId",
                "2",
                "-CentralHost",
                "192.168.137.1",
                "-ExpectedWifiSsid",
                "DZH 2053",
                "-DryRun",
            ],
            cwd=output,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
        assert "Seat 2" in dry_run.stdout
        assert "http://192.168.137.1" in dry_run.stdout
        assert "DZH 2053" in dry_run.stdout
        assert "maintenance PIN" in dry_run.stdout
        assert "provisioning password" in dry_run.stdout

        packaged_deployer = output / "scripts" / "DEPLOY_TABLET.ps1"
        assert packaged_deployer.read_bytes().startswith(b"\xef\xbb\xbf")
        windows_dry_run = subprocess.run(
            [
                _windows_powershell(),
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(packaged_deployer),
                "-SeatId",
                "2",
                "-CentralHost",
                "192.168.137.1",
                "-ExpectedWifiSsid",
                "DZH 2053",
                "-DryRun",
            ],
            cwd=output,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert windows_dry_run.returncode == 0, (
            windows_dry_run.stdout + windows_dry_run.stderr
        )
    finally:
        if output.exists():
            shutil.rmtree(output)
        archive = output.with_suffix(".zip")
        if archive.exists():
            archive.unlink()


def test_builder_rejects_artifacts_prefix_sibling_without_deleting_it(
    tmp_path: Path,
) -> None:
    platform_tools = tmp_path / "platform-tools"
    platform_tools.mkdir()
    for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt"):
        (platform_tools / name).write_bytes(b"fixture")
    apk = tmp_path / "SmartDeskTablet.apk"
    apk.write_bytes(b"fixture-apk")
    escaped = ROOT / f"artifacts-escape-test-{uuid.uuid4().hex}"
    escaped.mkdir()
    sentinel = escaped / "must-survive.txt"
    sentinel.write_text("owned by the caller", encoding="utf-8")

    try:
        result = subprocess.run(
            [
                _pwsh(),
                "-NoLogo",
                "-NoProfile",
                "-File",
                str(BUILD_SCRIPT),
                "-OutputDirectory",
                str(escaped),
                "-PlatformToolsDirectory",
                str(platform_tools),
                "-ApkPath",
                str(apk),
                "-SkipBuild",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode != 0
        assert sentinel.read_text(encoding="utf-8") == "owned by the caller"
    finally:
        if escaped.exists():
            shutil.rmtree(escaped)
        archive = escaped.with_suffix(".zip")
        if archive.exists():
            archive.unlink()


def test_deployer_applies_to_confirmed_device_and_verifies_result(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    shutil.copytree(ROOT / "deployment" / "tablet" / "package", package)
    (package / "payload").mkdir()
    (package / "platform-tools").mkdir()
    (package / "payload" / "SmartDeskTablet.apk").write_bytes(b"apk")
    (package / "package-manifest.json").write_text(
        json.dumps({
            "versionName": "0.9.0",
            "apkSha256": hashlib.sha256(b"apk").hexdigest(),
        }),
        encoding="utf-8",
    )
    (package / "deployment-defaults.json").write_text(
        json.dumps({"centralHost": "192.168.137.1", "expectedWifiSsid": ""}),
        encoding="utf-8",
    )
    shutil.copy2(
        ROOT / "scripts" / "manage_android_tablet.ps1",
        package / "scripts" / "manage_android_tablet.ps1",
    )
    adb_log = tmp_path / "adb.log"
    fake_adb = tmp_path / "fake-adb.ps1"
    fake_adb.write_text(
        f'''$line = $args -join " "
Add-Content -LiteralPath '{adb_log}' -Value $line -Encoding UTF8
if ($line -eq "devices") {{
  "List of devices attached"
  "FAKE-SERIAL device"
}} elseif ($line -match "getprop ro.product.manufacturer") {{ "Xiaomi" }}
elseif ($line -match "getprop ro.product.model") {{ "Test Tablet" }}
elseif ($line -match "install -r") {{ "Success" }}
elseif ($line -match "dumpsys package") {{
  "versionName=0.9.0"
  "android.permission.CAMERA: granted=true"
  "android.permission.RECORD_AUDIO: granted=true"
}} elseif ($line -match "resolve-activity") {{ "com.smartdesk.tablet/.MainActivity" }}
elseif ($line -match "settings get global stay_on_while_plugged_in") {{ "7" }}
elseif ($line -match "locksettings get-disabled") {{ "true" }}
elseif ($line -match "dumpsys deviceidle whitelist") {{ "system,com.smartdesk.tablet,10001" }}
elseif ($line -match "cmd wifi status") {{ "connected to DZH 2053" }}
elseif ($line -match "dumpsys activity activities") {{ "com.smartdesk.tablet/.MainActivity" }}
elseif ($line -match "logcat -d") {{ "WebView loaded: http://192.168.137.1:5173/seat/2" }}
else {{ "OK" }}
exit 0
''',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            _pwsh(),
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(package / "scripts" / "DEPLOY_TABLET.ps1"),
            "-SeatId",
            "2",
            "-CentralHost",
            "192.168.137.1",
            "-ExpectedWifiSsid",
            "DZH 2053",
            "-Serial",
            "FAKE-SERIAL",
            "-AdbPath",
            str(fake_adb),
            "-ConfirmTarget",
            "-SkipManualWait",
        ],
        cwd=package,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(
        (package / "reports" / "seat-02.json").read_text(encoding="utf-8-sig")
    )
    assert all(item["status"] == "PASS" for item in report["results"])
    commands = adb_log.read_text(encoding="utf-8-sig")
    assert "com.smartdesk.tablet.extra.DEPLOYMENT_SEAT_ID 2" in commands
    assert (
        "com.smartdesk.tablet.extra.DEPLOYMENT_CENTRAL_HOST "
        "http://192.168.137.1" in commands
    )


@pytest.mark.parametrize("apk_sha256", [None, "0" * 64])
def test_deployer_rejects_missing_or_mismatched_apk_hash_before_adb(
    tmp_path: Path,
    apk_sha256: str | None,
) -> None:
    package = tmp_path / "package"
    shutil.copytree(ROOT / "deployment" / "tablet" / "package", package)
    (package / "payload").mkdir()
    (package / "payload" / "SmartDeskTablet.apk").write_bytes(b"apk")
    manifest = {"versionName": "0.9.0"}
    if apk_sha256 is not None:
        manifest["apkSha256"] = apk_sha256
    (package / "package-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (package / "deployment-defaults.json").write_text(
        json.dumps({"centralHost": "192.168.137.1", "expectedWifiSsid": ""}),
        encoding="utf-8",
    )
    shutil.copy2(
        ROOT / "scripts" / "manage_android_tablet.ps1",
        package / "scripts" / "manage_android_tablet.ps1",
    )
    adb_log = tmp_path / "adb.log"
    fake_adb = tmp_path / "fake-adb.ps1"
    fake_adb.write_text(
        f'Add-Content -LiteralPath "{adb_log}" -Value ($args -join " ")',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            _pwsh(),
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(package / "scripts" / "DEPLOY_TABLET.ps1"),
            "-SeatId",
            "2",
            "-CentralHost",
            "192.168.137.1",
            "-AdbPath",
            str(fake_adb),
            "-ConfirmTarget",
        ],
        cwd=package,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    assert result.returncode != 0
    assert "SHA-256" in result.stdout + result.stderr
    assert not adb_log.exists()
