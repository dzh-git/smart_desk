"""
Phase 6 contract acceptance tests — start.bat, kill.bat, .gitignore, config.

ALL tests assert the TARGET contract.  Tests that FAIL due to missing
production code are correct — they document gaps that ZCode must fix.

No empty `pass`, no conditional assertions, no skip/xfail.

Contract areas covered:
  A. start.bat — frontend host, backend address, ENABLE_SCREEN_STREAM opt-in,
     PID recording, no shell=True or arbitrary command injection
  B. kill.bat — PID file priority, port-specific cleanup, no broad
     taskkill /IM, safe degrade when PID file missing
  C. .gitignore — expected ignored patterns, no committed .exe/logs/screenshots
  D. requirements.txt — actual deps, Windows-only markers, no download/commit
     of third-party binaries
  E. MediaMTX version pinning, Control API path, network binding contracts
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


# ── Paths ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
START_BAT = PROJECT_ROOT / "start.bat"
KILL_BAT = PROJECT_ROOT / "kill.bat"
GITIGNORE = PROJECT_ROOT / ".gitignore"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"

# Well-known paths for screen-stream services
SCREEN_STREAM_DIR = PROJECT_ROOT / "host_services" / "screen_stream"
DISPLAY_AGENT_DIR = PROJECT_ROOT / "host_services" / "display_agent"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_text(path: Path) -> str:
    """Read file as UTF-8 text or raise if not found."""
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist")
    return path.read_text(encoding="utf-8")


def _has_non_comment_line(text: str, pattern: str) -> bool:
    """Check if a non-comment line matches the given regex pattern."""
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


def _find_ports_in_text(text: str, ports: list[int]) -> set[int]:
    """Return the set of known ports found in the text."""
    found = set()
    for line in text.splitlines():
        for port in ports:
            if re.search(rf'\b{port}\b', line):
                found.add(port)
    return found


# ══════════════════════════════════════════════════════════════════════════════
# A. start.bat Contract
# ══════════════════════════════════════════════════════════════════════════════


class TestStartBatContract:
    """start.bat must follow the screen-stream launch contract."""

    def test_start_bat_exists(self) -> None:
        """start.bat exists and is non-empty."""
        assert START_BAT.is_file(), f"{START_BAT} not found"
        text = _read_text(START_BAT)
        assert len(text.strip()) > 0, "start.bat is empty"

    def test_frontend_listens_on_0000(self) -> None:
        """Frontend Vite dev server is started with --host 0.0.0.0.

        The plan requires Vite to listen on 0.0.0.0 so LAN terminals can
        access /screen and /admin.  Current start.bat uses --host 127.0.0.1
        which only allows localhost.
        """
        text = _read_text(START_BAT)
        has_0000 = _has_non_comment_line(text, r'--host\s+0\.0\.0\.0')
        assert has_0000, (
            "start.bat must start Vite with --host 0.0.0.0 "
            "(LAN access required for terminal browsers). "
            "Current start.bat uses --host 127.0.0.1 which only allows localhost."
        )

    def test_backend_listens_on_127001_port8000(self) -> None:
        """Backend continues to listen on 127.0.0.1:8000.

        The backend must NOT listen on 0.0.0.0 — it stays loopback-only,
        accessed through the Vite proxy.
        """
        text = _read_text(START_BAT)
        has_uvicorn_127 = _has_non_comment_line(
            text, r'127\.0\.0\.1.*8000'
        ) or _has_non_comment_line(
            text, r'uvicorn.*--host\s+127\.0\.0\.1.*--port\s+8000'
        )
        assert has_uvicorn_127, (
            "Backend must listen on 127.0.0.1:8000. "
            "Current start.bat must bind to 127.0.0.1, not 0.0.0.0."
        )

    def test_enable_screen_stream_is_opt_in(self) -> None:
        """ENABLE_SCREEN_STREAM is an opt-in variable guarded by a conditional.

        The variable must be DEFINED in start.bat (so the screen-stream
        feature is explicitly listed) AND it must only be used inside an
        'if' conditional check, not set or called unconditionally.
        """
        text = _read_text(START_BAT)
        has_var = "ENABLE_SCREEN_STREAM" in text
        has_conditional = bool(re.search(
            r'if\s+.*ENABLE_SCREEN_STREAM', text, re.IGNORECASE
        ))
        assert has_var and has_conditional, (
            "start.bat must define ENABLE_SCREEN_STREAM and use it inside a "
            "conditional (if statement).  Currently the variable is either "
            f"missing (has_var={has_var}) or not conditionally checked "
            f"(has_conditional={has_conditional})."
        )

    def test_display_agent_and_stream_have_independent_guards(self) -> None:
        """Display Agent and screen supervisor use independent feature flags."""
        text = _read_text(START_BAT)
        lines = text.splitlines()

        def guarded_block(variable: str) -> str:
            guard_idx = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if re.search(
                        rf'^if\s+(?:/I\s+)?"?%{variable}%"?\s*==\s*"?true"?\s*\($',
                        line.strip(),
                        re.IGNORECASE,
                    )
                ),
                -1,
            )
            assert guard_idx >= 0, f"{variable}=true guard not found"
            depth = 0
            for i in range(guard_idx, len(lines)):
                depth += lines[i].count("(") - lines[i].count(")")
                if i > guard_idx and depth <= 0:
                    return "\n".join(lines[guard_idx + 1:i])
            raise AssertionError(f"unterminated {variable} guard")

        agent_block = guarded_block("ENABLE_DISPLAY_AGENT")
        stream_block = guarded_block("ENABLE_SCREEN_STREAM")
        assert _has_non_comment_line(agent_block, r'^@?start\b.*agent\.py')
        assert not _has_non_comment_line(agent_block, r'^@?start\b.*supervisor\.py')
        assert _has_non_comment_line(stream_block, r'^@?start\b.*supervisor\.py')
        assert not _has_non_comment_line(stream_block, r'^@?start\b.*agent\.py')

    def test_starts_as_current_user_normal_process(self) -> None:
        """Agent and supervisor run as current login user (not SYSTEM/service).

        The script must NOT use 'sc create', 'runas', or 'schtasks' to
        install as a service or run as a different user.
        """
        text = _read_text(START_BAT)
        has_service_install = _has_non_comment_line(
            text, r'sc\s+create|runas|schtasks.*create'
        )
        assert not has_service_install, (
            "start.bat must not install a Windows Service or use runas. "
            "Agent must run in the current user session."
        )

    def test_pid_files_recorded(self) -> None:
        """start.bat records PIDs for started processes.

        At minimum, backend.pid and frontend.pid must be recorded.
        When screen stream is enabled, display_agent.pid and
        screen_supervisor.pid should also be recorded.
        """
        text = _read_text(START_BAT)
        has_backend_pid = "backend.pid" in text
        has_frontend_pid = "frontend.pid" in text
        assert has_backend_pid, "start.bat must record backend.pid"
        assert has_frontend_pid, "start.bat must record frontend.pid"

    def test_no_shell_true_or_user_input_concatenation(self) -> None:
        """start.bat must not use shell=True patterns or dangerous variable expansion."""
        text = _read_text(START_BAT)
        dangerous = [
            (r'start\s+""\s+%[a-z]', "unquoted variable as command"),
            (r'call\s+%[a-z]', "call to a variable"),
        ]
        for pattern, desc in dangerous:
            match = re.search(pattern, text, re.IGNORECASE)
            assert not match, (
                f"Dangerous pattern '{desc}' found: {match.group()!r}"
            )

    def test_screen_stream_pid_files_when_enabled(self) -> None:
        """When ENABLE_SCREEN_STREAM=true, display_agent.pid and
        screen_supervisor.pid PID files are recorded."""
        text = _read_text(START_BAT)
        has_agent_pid = "display_agent.pid" in text
        has_supervisor_pid = "screen_supervisor.pid" in text
        assert has_agent_pid and has_supervisor_pid, (
            "When ENABLE_SCREEN_STREAM is enabled, start.bat must record "
            f"display_agent.pid ({has_agent_pid}) and "
            f"screen_supervisor.pid ({has_supervisor_pid})."
        )


# ══════════════════════════════════════════════════════════════════════════════
# B. kill.bat Contract
# ══════════════════════════════════════════════════════════════════════════════


class TestKillBatContract:
    """kill.bat must cleanly stop processes without collateral damage."""

    def test_kill_bat_exists(self) -> None:
        """kill.bat exists and is non-empty."""
        assert KILL_BAT.is_file(), f"{KILL_BAT} not found"
        text = _read_text(KILL_BAT)
        assert len(text.strip()) > 0, "kill.bat is empty"

    def test_uses_pid_file_for_process_stopping(self) -> None:
        """kill.bat reads PID files first to stop known processes."""
        text = _read_text(KILL_BAT)
        assert "backend.pid" in text, "kill.bat must read backend.pid"
        assert "frontend.pid" in text, "kill.bat must read frontend.pid"

    def test_port_cleanup_only_specific_ports(self) -> None:
        """Port cleanup targets only known SmartDesk ports in kill.bat.

        Must include at minimum 8000 (backend) and 5173 (frontend).
        Should also include 8766 (Agent) and 8889 (MediaMTX HTTP) when
        screen stream is part of the project.
        """
        text = _read_text(KILL_BAT)
        found_ports = _find_ports_in_text(text, [8000, 5173, 8766, 8889])

        assert 8000 in found_ports, (
            "Port 8000 (backend) must be in kill list for cleanup"
        )
        assert 5173 in found_ports, (
            "Port 5173 (frontend) must be in kill list for cleanup"
        )
        assert 8766 in found_ports, (
            "Port 8766 (Display Agent) must be in kill list for cleanup"
        )
        assert 8889 in found_ports, (
            "Port 8889 (MediaMTX WebRTC HTTP) must be in kill list for cleanup"
        )

    def test_no_broad_taskkill_by_image_name(self) -> None:
        """kill.bat must NOT use 'taskkill /IM python.exe' or similar broad patterns."""
        text = _read_text(KILL_BAT)
        broad_patterns = [
            r'taskkill.*/IM\s+python',
            r'taskkill.*/IM\s+ffmpeg',
            r'taskkill.*/IM\s+mediamtx',
            r'taskkill.*/IM\s+node',
        ]
        for pattern in broad_patterns:
            has_broad = _has_non_comment_line(text, pattern)
            assert not has_broad, (
                f"kill.bat must not use broad taskkill /IM: '{pattern}'. "
                "Use PID files or port-based killing instead."
            )

    def test_does_not_kill_unrelated_python_processes(self) -> None:
        """kill.bat avoids killing Python processes outside SmartDesk.

        The script must use PID files, window titles, or port matching.
        """
        text = _read_text(KILL_BAT)
        has_pid_based = "backend.pid" in text
        has_title_based = "WINDOWTITLE" in text or "SmartDesk" in text
        assert has_pid_based or has_title_based, (
            "kill.bat must use PID files or SmartDesk-specific window title matching"
        )

    def test_pid_file_missing_safe_degrade(self) -> None:
        """When PID files are missing, kill.bat degrades gracefully (no crash)."""
        text = _read_text(KILL_BAT)
        assert "if exist" in text.lower(), (
            "kill.bat must check for file existence before reading PID files"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C. .gitignore Contract
# ══════════════════════════════════════════════════════════════════════════════


class TestGitignoreContract:
    """.gitignore must exclude screen-stream runtime artifacts."""

    def test_gitignore_exists(self) -> None:
        """.gitignore exists."""
        assert GITIGNORE.is_file(), f"{GITIGNORE} not found"

    def test_smartdesk_runtime_ignored(self) -> None:
        """.gitignore ignores .smartdesk-runtime/."""
        text = _read_text(GITIGNORE)
        assert ".smartdesk-runtime" in text, (
            ".gitignore must ignore .smartdesk-runtime/ (runtime state directory)"
        )

    def test_tools_ffmpeg_ignored(self) -> None:
        """.gitignore ignores tools/ffmpeg/."""
        text = _read_text(GITIGNORE)
        assert "tools/ffmpeg" in text or "tools/ffmpeg/" in text, (
            ".gitignore must ignore tools/ffmpeg/ (FFmpeg binary, not committed)"
        )

    def test_tools_mediamtx_ignored(self) -> None:
        """.gitignore ignores tools/mediamtx/."""
        text = _read_text(GITIGNORE)
        assert "tools/mediamtx" in text or "tools/mediamtx/" in text, (
            ".gitignore must ignore tools/mediamtx/ (MediaMTX binary, not committed)"
        )

    def test_logs_ignored(self) -> None:
        """.gitignore ignores screen-stream logs (*.log or logs/)."""
        text = _read_text(GITIGNORE)
        assert "*.log" in text or "logs/" in text, (
            ".gitignore must have a *.log or logs/ pattern"
        )

    def test_pid_files_ignored(self) -> None:
        """.gitignore ignores PID files."""
        text = _read_text(GITIGNORE)
        # Either explicit *.pid pattern, or covered by .smartdesk-runtime/
        has_pid_pattern = "*.pid" in text
        has_runtime = ".smartdesk-runtime" in text
        assert has_pid_pattern or has_runtime, (
            ".gitignore must ignore PID files (either *.pid or "
            ".smartdesk-runtime/ covers the runtime directory)"
        )

    def test_probe_screenshots_ignored(self) -> None:
        """.gitignore ignores probe screenshots (probe_*.png or similar)."""
        text = _read_text(GITIGNORE)
        has_screenshot_pattern = bool(re.search(r'probe.*\.png|screenshot.*\.png|test-results', text))
        assert has_screenshot_pattern, (
            ".gitignore must ignore probe screenshots (e.g., probe_*.png)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# D. requirements.txt Contract
# ══════════════════════════════════════════════════════════════════════════════


class TestRequirementsContract:
    """requirements.txt declares actual dependencies with Windows markers."""

    def test_requirements_exists(self) -> None:
        """requirements.txt exists."""
        assert REQUIREMENTS.is_file(), f"{REQUIREMENTS} not found"

    def test_core_framework_declared(self) -> None:
        """Core Python framework packages are declared."""
        text = _read_text(REQUIREMENTS)
        for pkg in ["fastapi", "uvicorn", "sqlalchemy", "pydantic"]:
            assert pkg in text, (
                f"Core dependency '{pkg}' not found in requirements.txt"
            )

    def test_speech_deps_declared(self) -> None:
        """Speech/ASR dependencies are declared."""
        text = _read_text(REQUIREMENTS)
        for pkg in ["funasr", "torch", "numpy", "scipy", "soundfile"]:
            if pkg not in text:
                pytest.fail(
                    f"Speech dependency '{pkg}' not found in requirements.txt"
                )

    def test_testing_deps_declared(self) -> None:
        """Testing dependencies are declared."""
        text = _read_text(REQUIREMENTS)
        assert "pytest" in text, "Test dependency 'pytest' not found"
        assert "httpx" in text, "Test dependency 'httpx' not found"

    def test_no_download_or_commit_third_party_binary(self) -> None:
        """requirements.txt does not trigger automatic binary downloads.

        FFmpeg and MediaMTX must be hand-installed, not pip-installed.
        """
        text = _read_text(REQUIREMENTS)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            for binary in ["ffmpeg", "mediamtx"]:
                assert binary not in stripped.lower(), (
                    f"requirements.txt must not reference '{binary}' "
                    f"in non-comment lines.  FFmpeg and MediaMTX are "
                    f"hand-installed, not pip packages. "
                    f"Offending line: {stripped}"
                )


# ══════════════════════════════════════════════════════════════════════════════
# E. MediaMTX Configuration Contract
# ══════════════════════════════════════════════════════════════════════════════


class TestMediaMTXConfigContract:
    """Configuration files must correctly define network bindings and version."""

    MEDIAMTX_TEMPLATE = PROJECT_ROOT / "host_services" / "screen_stream" / "mediamtx.template.yml"

    def test_mediamtx_version_pinned(self) -> None:
        """MediaMTX version must be pinned to a specific semver (X.Y.Z).

        The README must reference an exact version like "MediaMTX 1.19.0".
        A vague "v1.x" is not sufficient.
        """
        readme = PROJECT_ROOT / "host_services" / "screen_stream" / "README.md"
        if not readme.is_file():
            pytest.fail("README.md not found — version pin cannot be verified")
        text = _read_text(readme)
        match = re.search(
            r'MediaMTX[\s\-–—]*(?:v|version)?\s*(\d+\.\d+\.\d+)',
            text, re.IGNORECASE
        )
        assert match is not None, (
            "No exact MediaMTX version pinned in README. "
            "Need a pattern like 'MediaMTX 1.19.0'."
        )
        version = match.group(1)
        parts = version.split(".")
        assert len(parts) == 3, f"Pinned version '{version}' must be three-part semver"
        assert all(p.isdigit() for p in parts), f"Version '{version}' parts must be numeric"

    def test_control_api_path_v3(self) -> None:
        """Control API must use /v3/paths/list for MediaMTX 1.19.x.

        The backend _read_mediamtx_paths must reference /v3/paths/list,
        not the old /v2/paths from v1.17.
        """
        from backend.api import host_display as hd
        import inspect
        source = inspect.getsource(hd._read_mediamtx_paths)
        assert "/v3/paths/list" in source or "/v3/paths" in source, (
            "_read_mediamtx_paths uses /v2/paths — must update to "
            "/v3/paths/list for MediaMTX 1.19.x"
        )

    def test_network_binding_contract(self) -> None:
        """Verify network binding in mediamtx.template.yml.

        - RTSP only on 127.0.0.1
        - Control API only on 127.0.0.1
        - Metrics only on 127.0.0.1
        - WebRTC HTTP on 0.0.0.0 (LAN accessible)
        """
        if not self.MEDIAMTX_TEMPLATE.is_file():
            pytest.fail("mediamtx.template.yml not found")

        text = _read_text(self.MEDIAMTX_TEMPLATE)

        # RTSP must bind 127.0.0.1
        rtsp_loopback = bool(re.search(r'rtspAddress\s*.*127\.0\.0\.1', text))
        assert rtsp_loopback, (
            "RTSP address must bind 127.0.0.1. "
            "Currently the template does not explicitly restrict it."
        )

        # Control API must bind 127.0.0.1
        api_loopback = bool(re.search(r'apiAddress\s*.*127\.0\.0\.1', text))
        assert api_loopback, (
            "Control API address must bind 127.0.0.1."
        )

        # Metrics must bind 127.0.0.1
        metrics_loopback = bool(re.search(r'metricsAddress\s*.*127\.0\.0\.1', text))
        assert metrics_loopback, (
            "Metrics address must bind 127.0.0.1."
        )

        # WebRTC HTTP must NOT bind 127.0.0.1 (LAN accessible)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped.startswith("webrtcAddress"):
                assert "127.0.0.1" not in stripped, (
                    f"WebRTC HTTP must be LAN accessible (not bound to 127.0.0.1). "
                    f"Found: {stripped}"
                )


# ══════════════════════════════════════════════════════════════════════════════
# F. Screen-stream service files existence
# ══════════════════════════════════════════════════════════════════════════════


class TestScreenStreamFilesContract:
    """Expected screen-stream service files exist in host_services/."""

    def test_screen_stream_directory_exists(self) -> None:
        """host_services/screen_stream/ exists."""
        assert SCREEN_STREAM_DIR.is_dir(), "host_services/screen_stream/ not found"

    def test_display_agent_directory_exists(self) -> None:
        """host_services/display_agent/ exists."""
        assert DISPLAY_AGENT_DIR.is_dir(), "host_services/display_agent/ not found"

    def test_supervisor_script_exists(self) -> None:
        """screen_stream/supervisor.py exists."""
        assert (SCREEN_STREAM_DIR / "supervisor.py").is_file(), "supervisor.py not found"

    def test_config_json_exists(self) -> None:
        """screen_stream/config.json exists."""
        assert (SCREEN_STREAM_DIR / "config.json").is_file(), "config.json not found"

    def test_mediamtx_template_exists(self) -> None:
        """screen_stream/mediamtx.template.yml exists."""
        assert (SCREEN_STREAM_DIR / "mediamtx.template.yml").is_file(), "mediamtx.template.yml not found"
