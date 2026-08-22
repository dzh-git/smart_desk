"""Contract tests for the console-free SmartDesk meeting controller."""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER = PROJECT_ROOT / "smartdesk_control.ps1"
VBS_LAUNCHER = PROJECT_ROOT / "SmartDeskControl.vbs"
START_BAT = PROJECT_ROOT / "start.bat"
SHORTCUT_CREATOR = PROJECT_ROOT / "CreateSmartDeskShortcut.vbs"
ICON = PROJECT_ROOT / "assets" / "SmartDeskControl.ico"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_controller_files_exist() -> None:
    assert CONTROLLER.is_file()
    assert VBS_LAUNCHER.is_file()
    assert SHORTCUT_CREATOR.is_file()
    assert ICON.is_file()


def test_vbs_starts_controller_without_a_console() -> None:
    text = _read(VBS_LAUNCHER)
    assert "smartdesk_control.ps1" in text
    assert "pwsh.exe" in text
    assert "-STA" in text
    assert "-WindowStyle Hidden" in text
    assert re.search(r"shell\.Run\s+command,\s*0,\s*False", text, re.IGNORECASE)


def test_shortcut_creator_uses_project_icon() -> None:
    text = _read(SHORTCUT_CREATOR)
    assert "SmartDeskControl.vbs" in text
    assert "assets\\SmartDeskControl.ico" in text
    assert "CreateShortcut" in text
    assert "IconLocation" in text
    assert "%SystemRoot%\\System32\\wscript.exe" in text

    data = ICON.read_bytes()
    reserved, icon_type, image_count = struct.unpack_from("<HHH", data)
    assert reserved == 0
    assert icon_type == 1
    assert image_count == 7


def test_controller_uses_brand_icon_for_form_and_tray() -> None:
    text = _read(CONTROLLER)
    assert "assets\\SmartDeskControl.ico" in text
    assert "$script:form.Icon = $appIcon" in text
    assert "$script:trayIcon.Icon = $appIcon" in text


def test_controller_launches_batch_files_hidden() -> None:
    text = _read(CONTROLLER)
    assert "$processInfo.CreateNoWindow = $true" in text
    assert "ProcessWindowStyle]::Hidden" in text
    assert "start.bat" in text
    assert "kill.bat" in text
    assert "SMARTDESK_SKIP_BROWSER = 'true'" in text
    assert "SMARTDESK_CONTROL_MODE = 'true'" in text
    assert "SKIP_PAUSE = '1'" in text


def test_close_hides_but_tray_exit_stops_services() -> None:
    text = _read(CONTROLLER)
    assert "protected override void OnFormClosing" in text
    assert "if (!AllowExit)" in text
    assert "e.Cancel = true;" in text
    assert "Hide();" in text
    assert "$script:form = [SmartDeskControlForm]::new()" in text
    assert "$script:form.Show()" in text
    assert "[System.Windows.Forms.Application]::Run()" in text

    assert "$exitMenuItem = $trayMenu.Items.Add('结束程序')" in text
    assert "Stop-MeetingServices -ExitAfterStop" in text
    assert "$script:form.AllowExit = $true" in text
    assert "[System.Windows.Forms.Application]::Exit()" in text


def test_controller_has_required_controls_and_tray_icon() -> None:
    text = _read(CONTROLLER)
    for required_text in (
        "启动程序",
        "停止程序",
        "打开会议页面",
        "NotifyIcon",
        "ContextMenuStrip",
        "SmartDesk 会议控制",
    ):
        assert required_text in text


def test_controller_defines_operation_states_and_progress_bar() -> None:
    text = _read(CONTROLLER)
    for state in (
        "Stopped",
        "Starting",
        "Running",
        "Stopping",
        "OpeningPage",
        "Partial",
        "Error",
    ):
        assert f"'{state}'" in text

    assert "[System.Windows.Forms.ProgressBar]::new()" in text
    assert "$script:progressBar.Maximum = 100" in text
    assert "$progressTimer.Interval = 100" in text
    assert "[Math]::Min(" in text
    assert "92," in text


def test_active_operation_has_priority_over_health_polling() -> None:
    text = _read(CONTROLLER)
    status_function = text.split("function Update-ServiceStatus", 1)[1].split(
        "function Update-OperationProgress", 1
    )[0]
    for state in ("Starting", "Stopping", "OpeningPage"):
        assert f"'{state}' {{" in status_function
    assert status_function.count("return") >= 4

    assert "正在启动会议系统，请稍候…" in text
    assert "正在停止会议系统…" in text
    assert "正在打开会议页面…" in text


def test_operations_disable_conflicting_buttons_and_recover_from_health() -> None:
    text = _read(CONTROLLER)
    disable_function = re.search(
        r"function Disable-ActionButtons\s*\{(?P<body>.*?)\n\}",
        text,
        re.DOTALL,
    )
    assert disable_function is not None
    body = disable_function.group("body")
    assert "$script:startButton.Enabled = $false" in body
    assert "$script:stopButton.Enabled = $false" in body
    assert "$script:openButton.Enabled = $false" in body
    assert "Set-ActionButtonsFromHealth" in text


def test_progress_completes_only_on_real_service_state() -> None:
    text = _read(CONTROLLER)
    assert "if ($backendOnline -and $frontendOnline)" in text
    assert "Complete-ControllerOperation -FinalState 'Running'" in text
    assert "if (-not $backendOnline -and -not $frontendOnline)" in text
    assert "Complete-ControllerOperation -FinalState 'Stopped'" in text
    assert "$script:progressBar.Value = 100" in text
    assert "Test-OperationProcessEndedBeyondGrace" in text
    assert "control-start.log" in text
    assert "control-stop.log" in text


def test_backend_and_frontend_processes_are_hidden() -> None:
    text = _read(START_BAT)
    assert "-WindowStyle Normal" not in text
    backend_line = next(line for line in text.splitlines() if "backend.main:app" in line)
    frontend_line = next(line for line in text.splitlines() if "npm.cmd" in line and "run dev" in line)
    assert "-WindowStyle Hidden" in backend_line
    assert "-WindowStyle Hidden" in frontend_line


@pytest.mark.skipif(os.name != "nt", reason="WinForms self-test requires Windows")
def test_controller_self_test_runs_without_opening_ui() -> None:
    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell 7 is not installed")

    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-STA", "-File", str(CONTROLLER), "-SelfTest"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert '"startScriptExists":true' in result.stdout
    assert '"stopScriptExists":true' in result.stdout
    assert '"iconExists":true' in result.stdout
