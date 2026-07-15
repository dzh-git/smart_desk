"""
Phase 6 enhanced static launch-contract tests — verifies that start.bat's
PowerShell launch logic is structurally correct (stdout ≠ stderr paths,
process-alive check, pre-check invocation, stale-PID cleanup, no false
success on pre-check failure).

These tests parse start.bat to validate the launch contract statically. They
do NOT execute PowerShell (that requires a real host with FFmpeg/MediaMTX).
Like the core Phase 6 tests, they assert the TARGET contract and fail on
missing production code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
START_BAT = PROJECT_ROOT / "start.bat"


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist")
    return path.read_text(encoding="utf-8")


def _find_guard_block(text: str) -> tuple[int, int, str]:
    """Return (guard_idx, block_end, block_text) for the ENABLE_SCREEN_STREAM guard."""
    lines = text.splitlines()
    guard_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        batch_normalized = stripped.lower().lstrip("@").lstrip()
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith("::")
            or batch_normalized == "rem"
            or batch_normalized.startswith("rem ")
        ):
            continue
        if re.search(
            r'^if\s+(?:/I\s+)?["]?%ENABLE_SCREEN_STREAM%["]?\s*==\s*["]?true["]?\s*\($',
            stripped, re.IGNORECASE,
        ):
            guard_idx = i
            break

    if guard_idx < 0:
        return (-1, -1, "")

    depth = 0
    block_end = len(lines) - 1
    for i in range(guard_idx, len(lines)):
        stripped = lines[i].strip()
        if i == guard_idx:
            depth = stripped.count("(") - stripped.count(")")
            continue
        depth += stripped.count("(") - stripped.count(")")
        if depth <= 0:
            block_end = i
            break

    block_text = "\n".join(lines[guard_idx + 1 : block_end])
    return (guard_idx, block_end, block_text)


def _has_non_comment_line(text: str, pattern: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        batch_normalized = lowered.lstrip("@").lstrip()
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith("::")
            or batch_normalized == "rem"
            or batch_normalized.startswith("rem ")
        ):
            continue
        if re.search(pattern, stripped, re.IGNORECASE):
            return True
    return False


class TestStartBatRuntimeContract:
    """Validates start.bat's actual launch logic — beyond text structure."""

    def test_separate_stdout_and_stderr_paths(self) -> None:
        """PowerShell -RedirectStandardOutput and -RedirectStandardError must
        point to DIFFERENT files.  Passing the same path causes PowerShell to
        throw an error and the process never starts."""
        text = _read_text(START_BAT)
        # Find all pairs of (stdout, stderr) redirect arguments in the file
        stdout_paths = re.findall(
            r"-RedirectStandardOutput\s+'([^']+)'", text
        )
        stderr_paths = re.findall(
            r"-RedirectStandardError\s+'([^']+)'", text
        )
        assert len(stdout_paths) >= 2, (
            "Expected at least 2 -RedirectStandardOutput arguments "
            f"(agent + supervisor), found {len(stdout_paths)}"
        )
        assert len(stderr_paths) == len(stdout_paths), (
            f"Mismatch: {len(stdout_paths)} stdout vs {len(stderr_paths)} stderr"
        )
        for i, (so, se) in enumerate(zip(stdout_paths, stderr_paths)):
            assert so != se, (
                f"Start-Process redirect pair #{i + 1}: stdout and stderr "
                f"must point to DIFFERENT files, both are '{so}'. "
                "PowerShell throws 'RedirectStandardOutput and "
                "RedirectStandardError are the same'."
            )

    def test_supervisor_precheck_invoked(self) -> None:
        """start.bat must call 'supervisor.py --check' before launching
        agent and supervisor.  The pre-check validates config, binaries,
        and encoder availability."""
        text = _read_text(START_BAT)
        has_precheck = _has_non_comment_line(
            text, r"supervisor\.py.*--check"
        )
        assert has_precheck, (
            "start.bat must invoke 'supervisor.py --check' as a pre-check "
            "before starting the agent and supervisor.  No --check call found."
        )

    def test_precheck_failure_prevents_start_success(self) -> None:
        """When the pre-check fails (errorlevel != 0), start.bat must NOT
        proceed to start agent/supervisor.  It must set a failure flag and
        skip the start commands.

        The pre-check runs in a SEPARATE top-level block *before* the guard
        block, so that %SCREEN_STREAM_READY% expansion is correct (no delayed
        expansion needed).  The failure sets SCREEN_STREAM_READY=0, and the
        subsequent guard block checks this variable before starting services.
        """
        text = _read_text(START_BAT)
        lines = text.splitlines()

        # 1. Find the pre-check line: supervisor.py --check
        precheck_idx = -1
        for i, line in enumerate(lines):
            if re.search(r"supervisor\.py.*--check", line, re.IGNORECASE):
                precheck_idx = i
                break
        assert precheck_idx >= 0, "supervisor.py --check not found in start.bat"

        # 2. Check that there's an errorlevel check related to the pre-check
        #    within a few lines after it
        has_errorlevel_check = False
        has_flag_set = False
        for i in range(precheck_idx, min(precheck_idx + 6, len(lines))):
            stripped = lines[i].strip()
            if re.search(r"if\s+errorlevel\s+1", stripped, re.IGNORECASE):
                has_errorlevel_check = True
            if "SCREEN_STREAM_READY=0" in stripped:
                # Verify it's inside the errorlevel-handling context
                context = "\n".join(lines[precheck_idx : i + 1])
                has_flag_set = True

        assert has_errorlevel_check, (
            "start.bat must check 'if errorlevel 1' after supervisor.py --check "
            "to detect pre-check failure."
        )
        assert has_flag_set, (
            "After pre-check failure, start.bat must set SCREEN_STREAM_READY=0 "
            "so the subsequent guard block skips agent/supervisor startup."
        )

        # 3. Verify the guard block checks %SCREEN_STREAM_READY% before starting
        _, _, block_text = _find_guard_block(text)
        has_var_check = re.search(
            r"SCREEN_STREAM_READY%\s*EQU\s+1", block_text
        )
        assert has_var_check, (
            "The ENABLE_SCREEN_STREAM guard block must check "
            "%SCREEN_STREAM_READY% EQU 1 before starting agent/supervisor. "
            "When the pre-check (separate top-level block) sets "
            "SCREEN_STREAM_READY=0 on failure, this check prevents launch. "
            f"Block content:\n{block_text}"
        )

    def test_stale_pid_cleaned_before_start(self) -> None:
        """start.bat must delete stale PID files from previous runs before
        starting new processes, preventing false success from leftover files."""
        text = _read_text(START_BAT)
        # Look for PID file deletion lines BEFORE the start commands
        lines = text.splitlines()
        deleted_pids = set()
        reached_start = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if re.search(
                r"start\s+\"SmartDesk\s+(?:Display\s+Agent|Screen\s+Supervisor)\"",
                stripped,
            ):
                reached_start = True
            if re.search(r"del\s+.*display_agent\.pid", stripped, re.IGNORECASE):
                deleted_pids.add("display_agent")
            if re.search(r"del\s+.*screen_supervisor\.pid", stripped, re.IGNORECASE):
                deleted_pids.add("screen_supervisor")

        assert "display_agent" in deleted_pids, (
            "start.bat must delete display_agent.pid before starting, "
            "to prevent false success from a stale file."
        )
        assert "screen_supervisor" in deleted_pids, (
            "start.bat must delete screen_supervisor.pid before starting, "
            "to prevent false success from a stale file."
        )

    def test_start_command_verifies_process_alive(self) -> None:
        """The PowerShell start command must verify the process is still
        alive after launch (using HasExited or Get-Process), not just
        write the PID unconditionally."""
        text = _read_text(START_BAT)
        # Find the PowerShell -Command strings that start processes
        pws_commands = re.findall(
            r'Start-Process\s+python\.exe[^;]+;([^"]+)', text
        )
        # For each PowerShell command, verify it checks HasExited or Get-Process
        assert len(pws_commands) >= 2, (
            f"Expected at least 2 Start-Process commands, found {len(pws_commands)}"
        )

        for cmd in pws_commands:
            has_alive_check = (
                "HasExited" in cmd
                or "Get-Process" in cmd
            )
            assert has_alive_check, (
                "Each Start-Process command must verify the launched process "
                "is still alive (HasExited or Get-Process check). "
                f"Command missing check: {cmd.strip()[:80]}..."
            )

    def test_precheck_inside_screen_stream_section(self) -> None:
        """The supervisor.py --check call must be inside the screen-stream
        section (not at the top level), so it only runs when
        ENABLE_SCREEN_STREAM is processed."""
        text = _read_text(START_BAT)
        # Find the line number of the --check call
        lines = text.splitlines()
        check_line = -1
        for i, line in enumerate(lines):
            if re.search(r"supervisor\.py.*--check", line):
                check_line = i
                break

        assert check_line >= 0, "supervisor.py --check not found in start.bat"

        # Verify it's AFTER the host-display section header.
        header_line = -1
        for i, line in enumerate(lines):
            if "Host display services" in line:
                header_line = i
                break

        assert header_line >= 0, "Host display services section header not found"
        assert check_line > header_line, (
            f"supervisor.py --check at line {check_line + 1} must be inside "
            f"the screen-stream section (after header at line {header_line + 1})"
        )

    def test_log_files_match_section_paths(self) -> None:
        """Log file paths in start.bat must be under .smartdesk-runtime/
        and correctly use stdout/stderr suffixes."""
        text = _read_text(START_BAT)
        # Find all log paths referenced in Redirect arguments
        log_refs = re.findall(
            r"\.smartdesk-runtime\\([^\s'\"()]+\.(?:stdout|stderr)\.log)", text
        )
        assert len(log_refs) >= 4, (
            f"Expected at least 4 log file references (agent/stdout, agent/stderr, "
            f"supervisor/stdout, supervisor/stderr), found {len(log_refs)}"
        )
        # Each of the four expected files must appear
        expected = [
            r"display_agent\.stdout\.log",
            r"display_agent\.stderr\.log",
            r"screen_supervisor\.stdout\.log",
            r"screen_supervisor\.stderr\.log",
        ]
        for pat in expected:
            found = bool(re.search(pat, text))
            assert found, (
                f"Expected log file '{pat}' not referenced in start.bat"
            )
