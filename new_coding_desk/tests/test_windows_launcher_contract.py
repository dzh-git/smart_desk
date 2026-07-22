"""
Windows launcher contract tests -- validates that start.bat and kill.bat
meet the required launch contracts:

1. start.bat / kill.bat contain ONLY ASCII characters.
2. Files use CRLF line endings (no bare LF).
3. start.bat cleans stale backend.pid / frontend.pid before starting.
4. Frontend uses npm.cmd explicitly.
5. Backend / Frontend have independent stdout / stderr log files.
6. PID alive check after launch (Get-Process).
7. Port 8000 / 5173 polling with bounded retries (not fixed sleep).
8. Browser opens ONLY after 5173 is confirmed reachable.
9. On failure, does NOT print success message.
10. Browser uses PowerShell Start-Process.
11. Screen Stream conditional logic still present.
12. Regression: no unescaped parens in echo text; readiness poll loops
    wait ~1s between retries; browser opens only after 5173-ready; file
    stays ASCII / BOM-free / CRLF.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
START_BAT = PROJECT_ROOT / "start.bat"
KILL_BAT = PROJECT_ROOT / "kill.bat"


def _read_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist")
    return path.read_bytes()


def _read_text(path: Path) -> str:
    return _read_bytes(path).decode("utf-8")


def _is_crlf(path: Path) -> bool:
    data = _read_bytes(path)
    if not data:
        return True
    # No bare LF allowed (LF not preceded by CR)
    for i, b in enumerate(data):
        if b == 10:  # LF
            if i == 0 or data[i - 1] != 13:  # not preceded by CR
                return False
    # Must have at least one CRLF
    return b"\r\n" in data


# ======================================================================
# 1. ASCII-only
# ======================================================================


class TestAsciiOnly:
    """start.bat and kill.bat must contain ONLY ASCII characters (0-127)."""

    @pytest.mark.parametrize("bat_file", ["start.bat", "kill.bat"])
    def test_ascii_only(self, bat_file: str) -> None:
        path = PROJECT_ROOT / bat_file
        data = _read_bytes(path)
        non_ascii_positions = [i for i, b in enumerate(data) if b > 127]
        assert not non_ascii_positions, (
            f"{bat_file} contains {len(non_ascii_positions)} non-ASCII byte(s) "
            f"at positions: {non_ascii_positions[:20]}{'...' if len(non_ascii_positions) > 20 else ''}"
        )


# ======================================================================
# 2. CRLF line endings
# ======================================================================


class TestCRLF:
    """Files must use CRLF, no bare LF."""

    @pytest.mark.parametrize("bat_file", ["start.bat", "kill.bat"])
    def test_crlf_line_endings(self, bat_file: str) -> None:
        path = PROJECT_ROOT / bat_file
        assert _is_crlf(path), (
            f"{bat_file} must use CRLF line endings (no bare LF). "
            "CMD may misparse bare LF on Windows."
        )


# ======================================================================
# 3. Stale PID cleanup before start
# ======================================================================


class TestStalePidCleanup:
    """start.bat must delete backend.pid and frontend.pid before launching."""

    def test_backend_pid_cleaned(self) -> None:
        text = _read_text(START_BAT)
        # Must have a 'del' line for backend.pid BEFORE the backend start
        pid_del_idx = -1
        start_idx = -1
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if re.search(r"del\b.*backend\.pid", stripped, re.IGNORECASE):
                if pid_del_idx < 0:
                    pid_del_idx = i
            if re.search(r"uvicorn.*backend\.main", stripped, re.IGNORECASE):
                start_idx = i
        assert pid_del_idx >= 0, (
            "start.bat must delete backend.pid before starting. "
            "No 'del ...backend.pid' line found."
        )
        assert start_idx >= 0, "Backend start command not found in start.bat"
        assert pid_del_idx < start_idx, (
            f"backend.pid deletion (line {pid_del_idx + 1}) must come BEFORE "
            f"the backend start command (line {start_idx + 1})."
        )

    def test_frontend_pid_cleaned(self) -> None:
        text = _read_text(START_BAT)
        pid_del_idx = -1
        start_idx = -1
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if re.search(r"del\b.*frontend\.pid", stripped, re.IGNORECASE):
                if pid_del_idx < 0:
                    pid_del_idx = i
            if re.search(r"npm\.cmd.*run\s+dev", stripped, re.IGNORECASE):
                start_idx = i
        assert pid_del_idx >= 0, (
            "start.bat must delete frontend.pid before starting. "
            "No 'del ...frontend.pid' line found."
        )
        assert start_idx >= 0, "Frontend start command not found in start.bat"
        assert pid_del_idx < start_idx, (
            f"frontend.pid deletion (line {pid_del_idx + 1}) must come BEFORE "
            f"the frontend start command (line {start_idx + 1})."
        )


# ======================================================================
# 4. Frontend uses npm.cmd
# ======================================================================


class TestFrontendUsesNpmCmd:
    """Frontend must explicitly use npm.cmd (not just npm) for reliability."""

    def test_uses_npm_cmd(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"npm\.cmd", text), (
            "start.bat must use 'npm.cmd' (not 'npm') to explicitly invoke "
            "the Windows npm executable. Plain 'npm' may fail depending on "
            "PATH and file associations."
        )

    def test_npm_cmd_used_for_dev(self) -> None:
        text = _read_text(START_BAT)
        # npm.cmd is invoked via Start-Process -ArgumentList 'run dev ...'.
        # Accept either inline form ('run dev') or comma-separated form.
        has_npm_cmd = re.search(r"npm\.cmd", text)
        has_dev = re.search(r"run\s+dev", text)
        assert has_npm_cmd and has_dev, (
            "start.bat must use 'npm.cmd ... run dev' to start the frontend. "
            f"npm.cmd found: {bool(has_npm_cmd)}, 'run dev' found: {bool(has_dev)}"
        )


# ======================================================================
# 5. Independent stdout/stderr logs
# ======================================================================


class TestIndependentLogs:
    """Backend and Frontend must have separate stdout and stderr log files."""

    def test_backend_stdout_log(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"backend\.stdout\.log", text), (
            "start.bat must redirect backend stdout to "
            ".smartdesk-runtime/backend.stdout.log"
        )

    def test_backend_stderr_log(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"backend\.stderr\.log", text), (
            "start.bat must redirect backend stderr to "
            ".smartdesk-runtime/backend.stderr.log"
        )

    def test_frontend_stdout_log(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"frontend\.stdout\.log", text), (
            "start.bat must redirect frontend stdout to "
            ".smartdesk-runtime/frontend.stdout.log"
        )

    def test_frontend_stderr_log(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"frontend\.stderr\.log", text), (
            "start.bat must redirect frontend stderr to "
            ".smartdesk-runtime/frontend.stderr.log"
        )

    def test_backend_stdout_stderr_different(self) -> None:
        text = _read_text(START_BAT)
        # Find the backend Start-Process command
        # Look for the block that starts python with uvicorn backend.main
        # Extract all RedirectStandardOutput / RedirectStandardError pairs
        stdout_paths = re.findall(r"-RedirectStandardOutput\s+'([^']+)'", text)
        stderr_paths = re.findall(r"-RedirectStandardError\s+'([^']+)'", text)
        # All pairs must be different
        for i, (so, se) in enumerate(zip(stdout_paths, stderr_paths)):
            assert so != se, (
                f"Redirect pair #{i + 1}: stdout and stderr must point to "
                f"DIFFERENT files. Both are '{so}'."
            )


# ======================================================================
# 6. PID alive check
# ======================================================================


class TestPidAliveCheck:
    """After writing PID file, start.bat must verify the process is alive."""

    def test_backend_pid_alive_check(self) -> None:
        text = _read_text(START_BAT)
        lines = text.splitlines()
        # Find backend PID read and verify Get-Process check follows
        pid_read_idx = -1
        for i, line in enumerate(lines):
            if "BACKEND_PID" in line and re.search(
                r"set\s+/p\s+BACKEND_PID", line, re.IGNORECASE
            ):
                pid_read_idx = i
                break
        assert pid_read_idx >= 0, "Backend PID read (set /p BACKEND_PID) not found"

        # Within the next 10 lines, must have a Get-Process check
        found = False
        for i in range(pid_read_idx, min(pid_read_idx + 15, len(lines))):
            if "Get-Process" in lines[i] and "BACKEND_PID" in lines[i]:
                found = True
                break
        assert found, (
            "After reading BACKEND_PID, start.bat must verify the process is "
            "alive using Get-Process. No Get-Process check found near "
            f"line {pid_read_idx + 1}."
        )

    def test_frontend_pid_alive_check(self) -> None:
        text = _read_text(START_BAT)
        lines = text.splitlines()
        pid_read_idx = -1
        for i, line in enumerate(lines):
            if "FRONTEND_PID" in line and re.search(
                r"set\s+/p\s+FRONTEND_PID", line, re.IGNORECASE
            ):
                pid_read_idx = i
                break
        assert pid_read_idx >= 0, "Frontend PID read (set /p FRONTEND_PID) not found"

        found = False
        for i in range(pid_read_idx, min(pid_read_idx + 15, len(lines))):
            if "Get-Process" in lines[i] and "FRONTEND_PID" in lines[i]:
                found = True
                break
        assert found, (
            "After reading FRONTEND_PID, start.bat must verify the process is "
            "alive using Get-Process. No Get-Process check found near "
            f"line {pid_read_idx + 1}."
        )


# ======================================================================
# 7. Bounded port polling (not fixed sleep)
# ======================================================================


class TestBoundedPortPolling:
    """start.bat must poll ports with bounded retries, not fixed sleep."""

    def test_backend_port_polling_loop(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"Invoke-WebRequest.*127\.0\.0\.1:8000", text), (
            "start.bat must use Invoke-WebRequest to poll port 8000, "
            "not just a fixed timeout/sleep."
        )

    def test_frontend_port_polling_loop(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"Invoke-WebRequest.*127\.0\.0\.1:5173", text), (
            "start.bat must use Invoke-WebRequest to poll port 5173, "
            "not just a fixed timeout/sleep."
        )

    def test_backend_polling_bounded(self) -> None:
        text = _read_text(START_BAT)
        # Find "Waiting for backend" line, then look for FOR /L loop
        lines = text.splitlines()
        waiting_idx = -1
        for i, line in enumerate(lines):
            if "Waiting for backend" in line and "8000" in line:
                waiting_idx = i
                break
        assert waiting_idx >= 0, "Backend 'Waiting for 8000' line not found"
        bounded = False
        for i in range(waiting_idx, min(waiting_idx + 10, len(lines))):
            match = re.search(
                r"for\s+/L\s+%%?\w+\s+in\s+\(1,1,(\d+)\)",
                lines[i],
                re.IGNORECASE,
            )
            if match:
                upper = int(match.group(1))
                assert upper <= 60, (
                    f"Backend port polling loop upper bound ({upper}) "
                    f"is too large. Should be at most 60 seconds."
                )
                bounded = True
                break
        assert bounded, (
            "Backend port 8000 polling must use a bounded FOR /L loop. "
            "No bounded loop found after 'Waiting for backend' line."
        )

    def test_frontend_polling_bounded(self) -> None:
        text = _read_text(START_BAT)
        lines = text.splitlines()
        # Find "Waiting for frontend" line, then look for the FOR /L loop
        waiting_idx = -1
        for i, line in enumerate(lines):
            if "Waiting for frontend" in line and "5173" in line:
                waiting_idx = i
                break
        assert waiting_idx >= 0, "Frontend 'Waiting for 5173' line not found"
        # Look for FOR /L loop after the waiting line
        bounded = False
        for i in range(waiting_idx, min(waiting_idx + 10, len(lines))):
            # Match: for /L %%i in (1,1,30) do (  — %%i is batch variable syntax
            match = re.search(
                r"for\s+/L\s+%%?\w+\s+in\s+\(1,1,(\d+)\)",
                lines[i],
                re.IGNORECASE,
            )
            if match:
                upper = int(match.group(1))
                assert upper <= 60, (
                    f"Frontend port polling loop upper bound ({upper}) "
                    f"is too large. Should be at most 60 seconds."
                )
                bounded = True
                break
        assert bounded, (
            "Frontend port 5173 polling must use a bounded FOR /L loop. "
            "No bounded loop found after 'Waiting for frontend' line."
        )

    def test_no_simple_sleep_for_readiness(self) -> None:
        """After backend/frontend start, readiness must NOT rely solely on
        a fixed timeout. Must use Invoke-WebRequest polling."""
        text = _read_text(START_BAT)
        lines = text.splitlines()
        # Find the "Waiting for backend" line
        for i, line in enumerate(lines):
            if "Waiting for backend" in line:
                # Within the next 10 lines, must have polling infrastructure
                # (FOR /L loop or Invoke-WebRequest), not just timeout
                section = "\n".join(lines[i:i + 10])
                has_polling = (
                    "Invoke-WebRequest" in section
                    or re.search(r"for\s+/L", section, re.IGNORECASE)
                )
                assert has_polling, (
                    f"Backend readiness after 'Waiting for backend' must use "
                    f"polling (FOR /L + Invoke-WebRequest), not just timeout. "
                    f"Section:\n{section}"
                )
                break


# ======================================================================
# 8. Browser opens ONLY after 5173 ready
# ======================================================================


class TestBrowserAfterFrontendReady:
    """Browser must open ONLY after frontend 5173 is confirmed reachable."""

    def test_browser_after_frontend_ready_check(self) -> None:
        text = _read_text(START_BAT)
        lines = text.splitlines()

        # Find "SmartDesk started successfully" line
        success_line_idx = -1
        browser_line_idx = -1
        frontend_ready_idx = -1

        for i, line in enumerate(lines):
            stripped = line.strip()
            if "SmartDesk started successfully" in stripped:
                success_line_idx = i
            if "Start-Process" in stripped and "5173" in stripped:
                browser_line_idx = i
            if "Frontend ready" in stripped:
                frontend_ready_idx = i

        assert browser_line_idx >= 0, (
            "start.bat must open the browser using PowerShell Start-Process"
        )
        assert frontend_ready_idx >= 0, (
            "start.bat must confirm frontend readiness before opening browser. "
            "No 'Frontend ready' message found."
        )
        assert browser_line_idx > frontend_ready_idx, (
            f"Browser open (line {browser_line_idx + 1}) must come AFTER "
            f"frontend readiness confirmation (line {frontend_ready_idx + 1})."
        )
        assert success_line_idx >= 0, (
            "start.bat must have a 'SmartDesk started successfully' message"
        )
        assert success_line_idx > frontend_ready_idx, (
            "Success message must appear AFTER frontend is confirmed ready"
        )


# ======================================================================
# 9. Failure does NOT print success
# ======================================================================


class TestFailureNoSuccess:
    """On startup failure, start.bat must NOT print the success message."""

    def test_success_message_after_all_checks(self) -> None:
        text = _read_text(START_BAT)
        lines = text.splitlines()

        # Find the success message and the last error check
        success_idx = -1
        last_error_exit = -1

        for i, line in enumerate(lines):
            if "SmartDesk started successfully" in line:
                success_idx = i
            if re.search(r"exit\s*/b\s+1", line, re.IGNORECASE):
                last_error_exit = i

        assert success_idx > last_error_exit, (
            "The success message must come AFTER all possible error/exit "
            f"points. Last 'exit /b 1' at line {last_error_exit + 1}, "
            f"success at line {success_idx + 1}."
        )

    def test_backend_fail_exits_before_success(self) -> None:
        """If backend fails to start or respond, must exit /b 1 before success."""
        text = _read_text(START_BAT)
        lines = text.splitlines()

        success_idx = -1
        backend_fail_exits = []

        in_backend_section = False
        for i, line in enumerate(lines):
            if "Starting backend" in line:
                in_backend_section = True
            if in_backend_section and "Starting frontend" in line:
                in_backend_section = False
            if in_backend_section and re.search(r"exit\s*/b\s+1", line, re.IGNORECASE):
                backend_fail_exits.append(i)
            if "SmartDesk started successfully" in line:
                success_idx = i

        assert success_idx >= 0, "Success message not found"
        for exit_idx in backend_fail_exits:
            assert exit_idx < success_idx, (
                f"Backend failure exit at line {exit_idx + 1} must come "
                f"before success message at line {success_idx + 1}."
            )

    def test_frontend_fail_exits_before_success(self) -> None:
        """If frontend fails to start or respond, must exit /b 1 before success."""
        text = _read_text(START_BAT)
        lines = text.splitlines()

        success_idx = -1
        frontend_fail_exits = []

        in_frontend_section = False
        for i, line in enumerate(lines):
            if "Starting frontend" in line and "Vite" in line:
                in_frontend_section = True
            if in_frontend_section and "Screen Stream" in line:
                in_frontend_section = False
            if in_frontend_section and re.search(r"exit\s*/b\s+1", line, re.IGNORECASE):
                frontend_fail_exits.append(i)
            if "SmartDesk started successfully" in line:
                success_idx = i

        assert success_idx >= 0, "Success message not found"
        for exit_idx in frontend_fail_exits:
            assert exit_idx < success_idx, (
                f"Frontend failure exit at line {exit_idx + 1} must come "
                f"before success message at line {success_idx + 1}."
            )


# ======================================================================
# 10. Browser uses PowerShell Start-Process
# ======================================================================


class TestBrowserStartProcess:
    """Browser must be opened using PowerShell Start-Process, not CMD start."""

    def test_uses_start_process(self) -> None:
        text = _read_text(START_BAT)
        # Must use Start-Process to open the browser URL
        assert re.search(r"Start-Process\s+'?http://127\.0\.0\.1:5173", text), (
            "start.bat must use PowerShell 'Start-Process' to open the browser "
            "URL, not CMD 'start http://...'."
        )

    def test_no_cmd_start_url(self) -> None:
        """Must NOT use bare 'start http://...' (CMD built-in)."""
        text = _read_text(START_BAT)
        lines = text.splitlines()
        for line in lines:
            stripped = line.strip()
            # Exclude PowerShell Start-Process lines
            if "Start-Process" in stripped:
                continue
            # Reject bare 'start http://...'
            if re.match(r"^start\s+https?://", stripped, re.IGNORECASE):
                pytest.fail(
                    f"Found bare CMD 'start URL' command: '{stripped}'. "
                    "Must use PowerShell Start-Process instead."
                )


# ======================================================================
# 11. Screen Stream conditional logic preserved
# ======================================================================


class TestScreenStreamPreserved:
    """Screen Stream conditional logic must remain intact."""

    def test_screen_stream_guard_exists(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(
            r'if\s+/I\s+"?%ENABLE_SCREEN_STREAM%"?\s*==\s*"?true"?',
            text,
            re.IGNORECASE,
        ), "ENABLE_SCREEN_STREAM guard block must exist in start.bat"

    def test_screen_stream_binary_check(self) -> None:
        text = _read_text(START_BAT)
        assert "ffmpeg.exe" in text, (
            "FFmpeg binary check must exist for Screen Stream"
        )
        assert "mediamtx.exe" in text, (
            "MediaMTX binary check must exist for Screen Stream"
        )

    def test_screen_stream_supervisor_precheck(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"supervisor\.py.*--check", text), (
            "supervisor.py --check pre-check must exist"
        )

    def test_screen_stream_ready_flag(self) -> None:
        text = _read_text(START_BAT)
        assert "SCREEN_STREAM_READY" in text, (
            "SCREEN_STREAM_READY flag must be used"
        )

    def test_screen_stream_agent_start(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"Start-Process.*agent\.py", text), (
            "Display Agent start must exist"
        )
        assert re.search(r"display_agent\.stdout\.log", text), (
            "Display Agent stdout log must exist"
        )
        assert re.search(r"display_agent\.stderr\.log", text), (
            "Display Agent stderr log must exist"
        )

    def test_screen_stream_supervisor_start(self) -> None:
        text = _read_text(START_BAT)
        assert re.search(r"Start-Process.*supervisor\.py", text), (
            "Screen Supervisor start must exist"
        )
        assert re.search(r"screen_supervisor\.stdout\.log", text), (
            "Screen Supervisor stdout log must exist"
        )
        assert re.search(r"screen_supervisor\.stderr\.log", text), (
            "Screen Supervisor stderr log must exist"
        )

    def test_screen_stream_disabled_message(self) -> None:
        text = _read_text(START_BAT)
        assert "screen-stream" in text.lower() and "disabled" in text.lower(), (
            "Screen Stream must show 'disabled' message when not enabled"
        )

    def test_screen_stream_not_block_basic_startup(self) -> None:
        """When Screen Stream binaries are missing, basic frontend/backend
        startup must still succeed. Screen Stream section must not cause
        'exit /b 1' when ENABLE_SCREEN_STREAM=true but binaries are missing."""
        text = _read_text(START_BAT)
        lines = text.splitlines()

        # Find lines between "Screen Stream (optional)" and "Step 4: Open browser"
        ss_start = -1
        browser_start = -1
        for i, line in enumerate(lines):
            if "[screen-stream]" in line.lower():
                ss_start = i
            if "Open browser" in line or "[4/4]" in line:
                browser_start = i
                break

        assert ss_start >= 0, "Screen Stream section not found"
        assert browser_start >= 0, "Browser step not found"

        ss_section = "\n".join(lines[ss_start:browser_start])

        # Must NOT have exit /b 1 in the "binaries not found" branch
        # The binaries-not-found message should just warn, not exit
        # Check that the missing-binaries block does NOT contain exit /b 1
        # (it should just echo warnings and continue)
        assert "exit /b 1" not in ss_section.lower() or ss_section.count("exit /b 1") == 0, (
            "Screen Stream missing-binaries branch must NOT exit with error. "
            "Basic frontend/backend startup should proceed."
        )


# ======================================================================
# 12. Regression: CMD parse safety + bounded readiness polling
# ======================================================================
#
# These tests guard against the specific real-world failure where:
#   - An `echo` inside an `if (...)` / `for (...)` block printed text
#     containing an unescaped `)` (e.g. "(PID 12345) already exited"),
#     which CMD mistook for the end of the block, producing the error
#     "此时不应有 already" (i.e. "already was unexpected at this time").
#   - The readiness poll loop ran 30 Invoke-WebRequest calls with no
#     inter-iteration delay, so a connection-refused (instant fail) path
#     burned through all 30 retries in well under 30 seconds, making the
#     "poll up to 30 seconds" contract meaningless.
#
# They intentionally scan ALL executable echo lines and BOTH poll loops,
# not just one fixed sentence, so the original bug class cannot regress.
# ======================================================================


def _strip_batch_comment(line: str) -> str:
    """Return the batch-relevant content of a line, dropping leading labels.

    A line is treated as a comment if it starts with `::` or `REM` (case
    insensitive, after an optional leading `@`). Comment lines return empty
    string so callers can skip them.
    """
    stripped = line.strip()
    if not stripped:
        return ""
    lowered = stripped.lower().lstrip("@").lstrip()
    if stripped.startswith("::"):
        return ""
    if lowered == "rem" or lowered.startswith("rem "):
        return ""
    return stripped


def _echo_text(line: str) -> str | None:
    """If the line is an executable `echo` statement, return its text argument.

    Returns None for `@echo off`, `echo.` (blank line), comment lines, and
    non-echo lines. The returned text is what CMD would print, used to scan
    for unescaped parentheses that break `if/for` block parsing.
    """
    content = _strip_batch_comment(line)
    if not content:
        return None
    # Normalize leading '@'
    body = content
    if body.startswith("@"):
        body = body[1:].lstrip()
    if not re.match(r"echo(?:\s|$)", body, re.IGNORECASE):
        return None
    # Drop the 'echo' keyword and following whitespace
    text = re.sub(r"^echo\s*", "", body, flags=re.IGNORECASE)
    return text


def _find_for_loop_block(lines: list[str], after_marker: str) -> tuple[int, int] | None:
    """Locate the first `for /L` loop that appears at/after a marker line.

    Returns (for_line_index, block_end_index) where block_end_index is the
    line index of the `)` that closes the loop body, or None if not found.
    Parenthesis nesting is tracked from the `for ... do (` line.
    """
    start = -1
    for i, line in enumerate(lines):
        if after_marker in line:
            start = i
            break
    if start < 0:
        return None

    for_idx = -1
    for i in range(start, len(lines)):
        content = _strip_batch_comment(lines[i])
        if re.search(r"for\s+/L\s+%", content, re.IGNORECASE):
            for_idx = i
            break
    if for_idx < 0:
        return None

    # Track parenthesis depth from the for line itself
    depth = 0
    for i in range(for_idx, len(lines)):
        content = lines[i].strip()
        depth += content.count("(") - content.count(")")
        if depth <= 0 and i > for_idx:
            return (for_idx, i)
    return None


class TestEchoNoUnescapedParens:
    """No executable `echo` line may contain an unescaped `(` or `)`.

    Inside `if (...)` / `for (...)` blocks, CMD treats the FIRST `)` as the
    end of the block. An echo like `echo Backend (PID %P%) already exited.`
    therefore aborts parsing with '<text> was unexpected at this time'.
    Escaping every such instance is fragile, so the contract is: echo text
    must simply NOT contain bare parentheses at all.
    """

    def test_no_echo_line_has_unescaped_parens(self) -> None:
        text = _read_text(START_BAT)
        offenders: list[tuple[int, str]] = []
        for i, line in enumerate(text.splitlines(), start=1):
            echo_text = _echo_text(line)
            if echo_text is None:
                continue
            # An escaped paren is "^(" or "^)" — those are allowed.
            stripped_escaped = echo_text.replace("^(", "").replace("^)", "")
            if "(" in stripped_escaped or ")" in stripped_escaped:
                offenders.append((i, line.strip()))
        assert not offenders, (
            "start.bat has executable `echo` lines containing unescaped "
            "'(' or ')'. Inside if/for blocks CMD misreads the ')' as the "
            "end of the block and aborts with '<word> was unexpected at "
            "this time'. Offending lines:\n  "
            + "\n  ".join(f"L{n}: {s}" for n, s in offenders)
        )

    def test_specific_known_bad_messages_fixed(self) -> None:
        """The exact messages that caused the original failure must be gone.

        This guards the specific regression even if the generic scan above
        were ever weakened; it searches for the parenthesised PID phrasing
        across the whole file rather than one literal sentence.
        """
        text = _read_text(START_BAT)
        bad_fragments = [
            "(PID %BACKEND_PID%)",
            "(PID %FRONTEND_PID%)",
            "already exited.",  # any '... already exited.' echo is the bug class
        ]
        # The "already exited." message is fine ONLY if it has no parens;
        # combined with the no-paren rule above this is belt-and-braces.
        for frag in ["(PID %BACKEND_PID%)", "(PID %FRONTEND_PID%)"]:
            assert frag not in text, (
                f"Unfixed parenthesised PID echo still present: {frag!r}"
            )
        # 'already exited' may still appear, but never with a '(' on the same
        # echo line.
        for line in text.splitlines():
            if _echo_text(line) and "already exited" in line.lower():
                assert "(" not in line and ")" not in line, (
                    f"'already exited' echo still has parens: {line.strip()!r}"
                )


class TestReadinessPollingWaitsBetweenRetries:
    """Each readiness poll loop must wait ~1 second on the failure path.

    Without a delay, 30 connection-refused retries complete almost
    instantly, so the loop does NOT actually wait up to 30 seconds. The
    failure branch (after the Invoke-WebRequest probe fails and the process
    is confirmed still alive) must sleep before the next iteration.
    """

    def _loop_body(self, marker: str) -> list[str]:
        text = _read_text(START_BAT)
        lines = text.splitlines()
        block = _find_for_loop_block(lines, marker)
        assert block is not None, f"No for /L polling loop found after {marker!r}"
        for_idx, end_idx = block
        return lines[for_idx : end_idx + 1]

    def test_backend_poll_loop_waits_on_failure(self) -> None:
        body = self._loop_body("Waiting for backend")
        joined = "\n".join(body)
        # Must use a real ~1s wait, not a trivially short one.
        assert re.search(r"timeout\.exe\s+/t\s+1\b", joined), (
            "Backend readiness loop must call 'timeout.exe /t 1' on the "
            "failure path so 30 retries actually span ~30 seconds, not "
            "fire instantly. Loop body:\n" + joined
        )
        # The wait must live INSIDE the loop body (it does, by construction).

    def test_frontend_poll_loop_waits_on_failure(self) -> None:
        body = self._loop_body("Waiting for frontend")
        joined = "\n".join(body)
        assert re.search(r"timeout\.exe\s+/t\s+1\b", joined), (
            "Frontend readiness loop must call 'timeout.exe /t 1' on the "
            "failure path so 30 retries actually span ~30 seconds, not "
            "fire instantly. Loop body:\n" + joined
        )

    def test_poll_loops_bounded_to_at_most_60(self) -> None:
        """Retry counts must have an upper bound (no unbounded polling)."""
        text = _read_text(START_BAT)
        bounds = [
            int(m.group(1))
            for m in re.finditer(
                r"for\s+/L\s+%%?\w+\s+in\s+\(1,1,(\d+)\)", text, re.IGNORECASE
            )
        ]
        assert bounds, "No bounded for /L readiness loops found"
        for b in bounds:
            assert b <= 60, f"Readiness loop bound {b} exceeds 60"

    def test_no_unbounded_sleep_replaces_readiness_check(self) -> None:
        """A long fixed sleep must NOT replace the readiness probe.

        The probe (Invoke-WebRequest) must still be present for both ports;
        the 1s waits are only inter-retry pacing, not the readiness signal.
        """
        text = _read_text(START_BAT)
        assert re.search(r"Invoke-WebRequest.*127\.0\.0\.1:8000", text), (
            "Backend readiness must still probe 8000 via Invoke-WebRequest"
        )
        assert re.search(r"Invoke-WebRequest.*127\.0\.0\.1:5173", text), (
            "Frontend readiness must still probe 5173 via Invoke-WebRequest"
        )


class TestBrowserOnlyAfterFrontendReadyStrict:
    """Browser open + success banner must follow the 5173-ready confirmation."""

    def test_browser_open_after_frontend_ready_and_success_gated(self) -> None:
        text = _read_text(START_BAT)
        lines = text.splitlines()

        ready_idx = -1
        browser_idx = -1
        success_idx = -1
        for i, line in enumerate(lines):
            s = line.strip()
            if "Frontend ready" in s and ready_idx < 0:
                ready_idx = i
            if "Start-Process" in s and "5173" in s:
                browser_idx = i
            if "SmartDesk started successfully" in s:
                success_idx = i

        assert ready_idx >= 0, "No 'Frontend ready' confirmation found"
        assert browser_idx >= 0, "No browser Start-Process 5173 line found"
        assert success_idx >= 0, "No success banner found"
        assert ready_idx < browser_idx, (
            f"Browser open (L{browser_idx + 1}) must come AFTER frontend "
            f"ready confirmation (L{ready_idx + 1})"
        )
        assert browser_idx < success_idx, (
            f"Success banner (L{success_idx + 1}) must come AFTER browser "
            f"open (L{browser_idx + 1}); never print success before opening"
        )

    def test_no_browser_open_before_frontend_poll_loop(self) -> None:
        """No Start-Process 5173 (browser) may appear before the frontend
        readiness poll loop begins."""
        text = _read_text(START_BAT)
        lines = text.splitlines()
        wait_idx = -1
        browser_idx = -1
        for i, line in enumerate(lines):
            if "Waiting for frontend" in line and "5173" in line:
                wait_idx = i
            if "Start-Process" in line and "5173" in line:
                browser_idx = i
        assert wait_idx >= 0 and browser_idx >= 0
        assert wait_idx < browser_idx, (
            "Browser must not open before the frontend readiness wait begins"
        )


class TestLauncherFileByteHygiene:
    """start.bat must remain ASCII-only, BOM-free, CRLF, no bare LF."""

    def test_start_bat_ascii_crlf_no_bom(self) -> None:
        data = _read_bytes(START_BAT)
        non_ascii = [i for i, b in enumerate(data) if b > 127]
        assert not non_ascii, f"non-ASCII bytes at {non_ascii[:10]}"
        assert data[:3] != b"\xef\xbb\xbf", "start.bat must not have a UTF-8 BOM"
        assert _is_crlf(START_BAT), "start.bat must use CRLF (no bare LF)"


class TestPowerShellInsideDelayedExpansion:
    """PowerShell commands must survive CMD delayed-expansion parsing."""

    def test_no_bang_negation_in_powershell_commands(self) -> None:
        text = _read_text(START_BAT)
        assert "!$exited" not in text, (
            "CMD delayed expansion consumes text between PowerShell '!$exited' "
            "tokens. Use PowerShell '-not $exited' instead."
        )

    def test_host_process_launches_use_powershell_not_operator(self) -> None:
        text = _read_text(START_BAT)
        host_launches = [
            line
            for line in text.splitlines()
            if "Start-Process" in line
            and ("agent.py" in line or "supervisor.py" in line)
        ]
        assert len(host_launches) == 2
        assert all("-and -not $exited" in line for line in host_launches)
