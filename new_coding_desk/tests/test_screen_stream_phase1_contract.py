"""
Phase 1 contract acceptance tests for SmartDesk screen stream service.

These tests define the CORRECT behavioral contract derived from the design
spec in working/SmartDesk 中央主机屏幕共享与应用切换计划.md.  Current
production code that violates the contract will fail with AssertionError —
this is EXPECTED and documents known gaps for ZCode to fix in a follow-up pass.

Contract areas covered:
  A. MediaMTX generated config (bindings, disabled protocols, placeholders)
  B. FFmpeg command (lavfi ddagrab, output_idx, framerate, encoding params)
  C. Encoder probe and display probe command contract
  D. Windows temporary file lifecycle (close before subprocess, cleanup)
  E. Config validation (illegal values rejected)
  F. Process safety (argv, no shell, bounded restart, no-download failure)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Path setup ──────────────────────────────────────────────────────────────

SCREEN_STREAM_DIR = (
    Path(__file__).resolve().parent.parent / "host_services" / "screen_stream"
)
_SYS_PATH_ENTRY = str(SCREEN_STREAM_DIR)
if _SYS_PATH_ENTRY not in sys.path:
    sys.path.insert(0, _SYS_PATH_ENTRY)

import supervisor
import encoder_probe
import display_probe

# Re-read template once at module level to avoid repeated I/O
MEDIAMTX_TEMPLATE = (SCREEN_STREAM_DIR / "mediamtx.template.yml").read_text(
    encoding="utf-8"
)

# Well-known defaults from config.json
RTSP_PORT = 8554
WEBRTC_HTTP_PORT = 8889
WEBRTC_UDP_PORT = 8189
STREAM_PATH = "screen"
CONTROL_API_PORT = 9997  # hardcoded in generate_mediamtx_config
METRICS_PORT = 9998  # hardcoded in generate_mediamtx_config


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _win_subprocess_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make Windows-only subprocess constants available on all platforms.

    Without this, encoder_probe._try_probe and display_probe functions raise
    AttributeError on Linux/macOS when they try to access
    subprocess.CREATE_NO_WINDOW.
    """
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):
        monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    if not hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        monkeypatch.setattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False,
        )


@pytest.fixture
def mediamtx_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Generate a MediaMTX config from the real template and return its text."""
    tpl = tmp_path / "mediamtx.template.yml"
    tpl.write_text(MEDIAMTX_TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(supervisor, "SCRIPT_DIR", tmp_path)

    cfg = {
        "rtsp_port": RTSP_PORT,
        "webrtc_http_port": WEBRTC_HTTP_PORT,
        "webrtc_udp_port": WEBRTC_UDP_PORT,
        "host_ip": "192.168.1.100",
        "stream_path": STREAM_PATH,
    }
    out = supervisor.generate_mediamtx_config(cfg, tmp_path)
    return out.read_text(encoding="utf-8")


@pytest.fixture
def ffmpeg_base_cfg() -> dict:
    """Sensible defaults for build_ffmpeg_command contract tests."""
    return {
        "display_index": 0,
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "bitrate": "5M",
        "rtsp_port": RTSP_PORT,
        "stream_path": STREAM_PATH,
    }


@pytest.fixture
def probe_config() -> dict:
    """A minimal ENCODER_CONFIG-style dict for _try_probe tests."""
    return {
        "name": "libx264",
        "requires_hw": False,
        "extra_args": [
            "-vf", "hwdownload,format=bgra,format=nv12",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-profile:v", "baseline",
            "-b:v", "5M",
            "-g", "30",
            "-bf", "0",
            "-pix_fmt", "yuv420p",
        ],
    }


# ── A. MediaMTX Config Contract ──────────────────────────────────────────────


class TestMediaMTXConfigContract:
    """The generated mediamtx.yml must enforce network security boundaries."""

    def test_rtsp_address_binds_127001(self, mediamtx_config: str) -> None:
        """RTSP publish address explicitly binds 127.0.0.1."""
        for line in mediamtx_config.splitlines():
            if line.strip().startswith("rtspAddress"):
                assert "127.0.0.1:" in line, (
                    f"RTSP must bind 127.0.0.1, got: {line.strip()}"
                )
                return
        pytest.fail("No rtspAddress found in generated config")

    def test_control_api_binds_127001(self, mediamtx_config: str) -> None:
        """Control API (apiAddress) explicitly binds 127.0.0.1."""
        for line in mediamtx_config.splitlines():
            if line.strip().startswith("apiAddress"):
                assert "127.0.0.1:" in line, (
                    f"Control API must bind 127.0.0.1, got: {line.strip()}"
                )
                return
        pytest.fail("No apiAddress found in generated config")

    def test_metrics_binds_127001(self, mediamtx_config: str) -> None:
        """Metrics address explicitly binds 127.0.0.1."""
        for line in mediamtx_config.splitlines():
            if line.strip().startswith("metricsAddress"):
                assert "127.0.0.1:" in line, (
                    f"Metrics must bind 127.0.0.1, got: {line.strip()}"
                )
                return
        pytest.fail("No metricsAddress found in generated config")

    def test_webrtc_http_not_bound_127001(self, mediamtx_config: str) -> None:
        """WebRTC HTTP address is LAN-accessible (not restricted to 127.0.0.1)."""
        for line in mediamtx_config.splitlines():
            if line.strip().startswith("webrtcAddress"):
                assert "127.0.0.1" not in line, (
                    f"WebRTC HTTP must be LAN-accessible, got: {line.strip()}"
                )
                return
        pytest.fail("No webrtcAddress found in generated config")

    def test_webrtc_udp_uses_configured_port(self, mediamtx_config: str) -> None:
        """WebRTC UDP is configured to use the port from config.json (8189)."""
        port_str = str(WEBRTC_UDP_PORT)
        known_udp_keys = [
            "webrtcICEUDPMuxAddress", "webrtcUDPAddress",
            "webrtcICEUDPMux", "webrtcUdpAddress",
            "webrtcLocalUDPAddress",
        ]
        found = False
        for line in mediamtx_config.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith("webrtcAddress"):
                continue
            if port_str in stripped and any(
                k.lower() in stripped.lower() for k in known_udp_keys
            ):
                found = True
                break
        assert found, (
            f"WebRTC UDP port {WEBRTC_UDP_PORT} not configured via any known "
            f"UDP key ({known_udp_keys}). The current template only uses "
            f"{WEBRTC_UDP_PORT} in comments. Add an explicit config key "
            f"(e.g. 'webrtcICEUDPMuxAddress: :{WEBRTC_UDP_PORT}') that uses "
            f"{{{{WEBRTC_UDP_PORT}}}} as its value."
        )

    def test_rtmp_disabled(self, mediamtx_config: str) -> None:
        """RTMP protocol is explicitly disabled (non-comment config line)."""
        for line in mediamtx_config.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped.startswith("rtmp:"):
                assert stripped in ("rtmp: no", "rtmp: false"), (
                    f"RTMP must be disabled, got: {stripped}"
                )
                return
        pytest.fail("No rtmp config directive found in non-comment lines")

    def test_hls_disabled(self, mediamtx_config: str) -> None:
        """HLS protocol is explicitly disabled (non-comment config line)."""
        for line in mediamtx_config.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped.startswith("hls:"):
                assert stripped in ("hls: no", "hls: false"), (
                    f"HLS must be disabled, got: {stripped}"
                )
                return
        pytest.fail("No hls config directive found in non-comment lines")

    def test_srt_disabled(self, mediamtx_config: str) -> None:
        """SRT protocol is explicitly disabled (non-comment config line)."""
        for line in mediamtx_config.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped.startswith("srt:"):
                assert stripped in ("srt: no", "srt: false"), (
                    f"SRT must be disabled, got: {stripped}"
                )
                return
        pytest.fail("No srt config directive found in non-comment lines")

    def test_moq_disabled(self, mediamtx_config: str) -> None:
        """MoQ protocol is explicitly disabled with 'moq: no'.

        Absence of a moq directive does NOT guarantee the protocol is
        disabled — default behavior depends on the MediaMTX version.
        """
        for line in mediamtx_config.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped.startswith("moq:"):
                assert stripped in ("moq: no", "moq: false", "moq: off"), (
                    f"MoQ must be explicitly disabled, got: {stripped}"
                )
                return
        pytest.fail(
            "MoQ must be explicitly disabled with 'moq: no' in a non-comment "
            "config line. Absence is not reliable — depends on MediaMTX version."
        )

    def test_stream_path_fixed_to_screen(self, mediamtx_config: str) -> None:
        """Stream path is 'screen' and appears as a key under the 'paths:' section."""
        import re
        match = re.search(r'^paths:', mediamtx_config, re.MULTILINE)
        assert match, "Config must have a 'paths:' section"
        after_paths = mediamtx_config[match.end():]
        assert re.search(
            rf'^\s+{STREAM_PATH}:', after_paths, re.MULTILINE
        ), (
            f"'{STREAM_PATH}' must be a key under the 'paths:' section"
        )

    def test_webrtc_additional_hosts_contains_host_ip(
        self, mediamtx_config: str
    ) -> None:
        """webrtcAdditionalHosts includes the configured HOST_IP."""
        for line in mediamtx_config.splitlines():
            if line.strip().startswith("webrtcAdditionalHosts"):
                assert "192.168.1.100" in line, (
                    f"webrtcAdditionalHosts must contain the configured host_ip, "
                    f"got: {line.strip()}"
                )
                return
        pytest.fail("No webrtcAdditionalHosts found in config")

    def test_no_unsubstituted_placeholders(self, mediamtx_config: str) -> None:
        """No {{...}} or {...}} placeholders remain after substitution."""
        assert "{{" not in mediamtx_config, (
            "Unsubstituted placeholder '{{' found in config"
        )
        assert "}}" not in mediamtx_config, (
            "Unsubstituted placeholder '}}' found in config"
        )


# ── B. FFmpeg Command Contract ────────────────────────────────────────────────


class TestFFmpegCommandContract:
    """FFmpeg argv must use lavfi ddagrab with output_idx (not -f ddagrab)."""

    ENCODERS = ["h264_nvenc", "h264_qsv", "libx264"]

    def test_uses_lavfi_not_ddagrab_format(self, ffmpeg_base_cfg: dict) -> None:
        """Input format is 'lavfi', not 'ddagrab'."""
        for enc in self.ENCODERS:
            cmd = supervisor.build_ffmpeg_command(
                ffmpeg_base_cfg, enc, Path("/ffmpeg")
            )
            f_idx = cmd.index("-f")
            fmt = cmd[f_idx + 1]
            assert fmt == "lavfi", (
                f"[{enc}] Must use -f lavfi, got -f {fmt}"
            )

    def test_input_uses_output_idx_not_desktop_idx(
        self, ffmpeg_base_cfg: dict
    ) -> None:
        """Input spec uses 'ddagrab=output_idx=N', not 'desktop_idx='."""
        for enc in self.ENCODERS:
            cmd = supervisor.build_ffmpeg_command(
                ffmpeg_base_cfg, enc, Path("/ffmpeg")
            )
            i_idx = cmd.index("-i")
            inp = cmd[i_idx + 1]
            assert "ddagrab=output_idx=" in inp, (
                f"[{enc}] Input must contain 'ddagrab=output_idx=', "
                f"got: {inp}"
            )
            assert "desktop_idx=" not in inp, (
                f"[{enc}] Input must not contain 'desktop_idx=', "
                f"got: {inp}"
            )

    def test_uses_configured_framerate_in_lavfi_input(
        self, ffmpeg_base_cfg: dict
    ) -> None:
        """Framerate is embedded in the lavfi filter (no separate -framerate flag)."""
        cfg = dict(ffmpeg_base_cfg, fps=30)
        for enc in self.ENCODERS:
            cmd = supervisor.build_ffmpeg_command(cfg, enc, Path("/ffmpeg"))
            i_idx = cmd.index("-i")
            inp = cmd[i_idx + 1]
            assert "framerate=30" in inp, (
                f"[{enc}] Framerate must be in lavfi input, got: {inp}"
            )
            assert "-framerate" not in cmd, (
                f"[{enc}] Must not use -framerate flag; use lavfi filter param"
            )

    def test_no_f_ddagrab_anywhere(self, ffmpeg_base_cfg: dict) -> None:
        """The string '-f ddagrab' does not appear in any encoder's command."""
        for enc in self.ENCODERS:
            cmd = supervisor.build_ffmpeg_command(
                ffmpeg_base_cfg, enc, Path("/ffmpeg")
            )
            as_str = " ".join(cmd)
            assert "-f ddagrab" not in as_str, (
                f"[{enc}] Command must not contain '-f ddagrab': {as_str}"
            )

    def test_no_desktop_idx_anywhere(self, ffmpeg_base_cfg: dict) -> None:
        """The string 'desktop_idx=' does not appear in any encoder's command."""
        for enc in self.ENCODERS:
            cmd = supervisor.build_ffmpeg_command(
                ffmpeg_base_cfg, enc, Path("/ffmpeg")
            )
            as_str = " ".join(cmd)
            assert "desktop_idx=" not in as_str, (
                f"[{enc}] Command must not contain 'desktop_idx=': {as_str}"
            )

    def test_bf0_gop30_noaudio_loopback(self, ffmpeg_base_cfg: dict) -> None:
        """Every encoder command includes bf=0, GOP 30, -an, loopback RTSP URL."""
        for enc in self.ENCODERS:
            cmd = supervisor.build_ffmpeg_command(
                ffmpeg_base_cfg, enc, Path("/ffmpeg")
            )
            # bf=0
            assert "-bf" in cmd, f"[{enc}] -bf flag missing"
            assert cmd[cmd.index("-bf") + 1] == "0", f"[{enc}] bf must be 0"
            # GOP 30
            assert "-g" in cmd, f"[{enc}] -g flag missing"
            assert cmd[cmd.index("-g") + 1] == "30", f"[{enc}] GOP must be 30"
            # No audio
            assert "-an" in cmd, f"[{enc}] -an flag missing"
            # Loopback RTSP URL
            loopback = f"rtsp://127.0.0.1:{RTSP_PORT}/{STREAM_PATH}"
            assert loopback in cmd, (
                f"[{enc}] Loopback RTSP URL missing, expected: {loopback}"
            )

    def test_libx264_has_hwdownload_and_format(self, ffmpeg_base_cfg: dict) -> None:
        """libx264 software fallback command uses shared D3D11_TO_NV12_FILTER."""
        cmd = supervisor.build_ffmpeg_command(
            ffmpeg_base_cfg, "libx264", Path("/ffmpeg")
        )
        vf_idx = cmd.index("-vf")
        flt = cmd[vf_idx + 1]
        assert flt == supervisor.D3D11_TO_NV12_FILTER, (
            f"libx264 must use shared D3D11_TO_NV12_FILTER, got: {flt}"
        )
        assert "bgra" in flt, f"BGRA conversion must be present in libx264 filter: {flt}"

    def test_qsv_has_hwdownload_filter(self, ffmpeg_base_cfg: dict) -> None:
        """h264_qsv command uses the same shared D3D11_TO_NV12_FILTER."""
        cmd = supervisor.build_ffmpeg_command(
            ffmpeg_base_cfg, "h264_qsv", Path("/ffmpeg")
        )
        vf_idx = cmd.index("-vf")
        flt = cmd[vf_idx + 1]
        assert flt == supervisor.D3D11_TO_NV12_FILTER, (
            f"h264_qsv must use shared D3D11_TO_NV12_FILTER, got: {flt}"
        )

    def test_nvenc_no_hwdownload(self, ffmpeg_base_cfg: dict) -> None:
        """h264_nvenc command must NOT have -vf — it keeps D3D11 hardware frames."""
        cmd = supervisor.build_ffmpeg_command(
            ffmpeg_base_cfg, "h264_nvenc", Path("/ffmpeg")
        )
        assert "-vf" not in cmd, (
            f"NVENC must not have -vf flag, got: {cmd}"
        )

    def test_includes_configured_resolution(self, ffmpeg_base_cfg: dict) -> None:
        """FFmpeg command specifies the configured width×height via video_size.

        The config has width=1920, height=1080, but build_ffmpeg_command
        currently ignores these values — making resolution depend on the
        display's native mode, which may not be 1080p.
        """
        cfg = dict(ffmpeg_base_cfg, width=1920, height=1080)
        cmd = supervisor.build_ffmpeg_command(cfg, "h264_nvenc", Path("/ffmpeg"))
        cmd_str = " ".join(cmd)
        # The lavfi ddagrab filter should specify video_size
        i_idx = cmd.index("-i")
        inp = cmd[i_idx + 1]
        assert "video_size=1920x1080" in inp, (
            f"Lavfi input must specify video_size=1920x1080. "
            f"Current command ignores width/height from config.\n"
            f"  input: {inp}\n"
            f"  cmd: {cmd_str}"
        )


# ── C. Probe Contract ─────────────────────────────────────────────────────────


class TestEncoderProbeContract:
    """encoder_probe._try_probe must construct commands matching the ddagrab contract."""

    def test_uses_lavfi_not_ddagrab_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        probe_config: dict,
    ) -> None:
        """Probe uses -f lavfi, not -f ddagrab."""
        captured: list[list[str]] = []
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, *a, **kw: (
                captured.append(cmd)
                or subprocess.CompletedProcess(cmd, 0, b"", b"")
            ),
        )
        monkeypatch.setattr(
            tempfile,
            "NamedTemporaryFile",
            _make_fake_tempfile(tmp_path / "probe.mp4"),
        )

        encoder_probe._try_probe(Path("/ffmpeg"), probe_config)
        assert len(captured) == 1, "subprocess.run was not called"
        cmd = captured[0]
        f_idx = cmd.index("-f")
        assert cmd[f_idx + 1] == "lavfi", (
            f"Probe must use -f lavfi, got -f {cmd[f_idx + 1]}"
        )

    def test_input_uses_output_idx(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        probe_config: dict,
    ) -> None:
        """Probe input contains ddagrab=output_idx=, not desktop_idx=."""
        captured: list[list[str]] = []
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, *a, **kw: (
                captured.append(cmd)
                or subprocess.CompletedProcess(cmd, 0, b"", b"")
            ),
        )
        monkeypatch.setattr(
            tempfile,
            "NamedTemporaryFile",
            _make_fake_tempfile(tmp_path / "probe.mp4"),
        )

        encoder_probe._try_probe(Path("/ffmpeg"), probe_config)
        assert len(captured) == 1
        cmd = captured[0]
        i_idx = cmd.index("-i")
        inp = cmd[i_idx + 1]
        assert "ddagrab=output_idx=" in inp, (
            f"Probe input must contain 'ddagrab=output_idx=', got: {inp}"
        )
        assert "desktop_idx=" not in inp, (
            f"Probe input must not contain 'desktop_idx=', got: {inp}"
        )

    def test_no_f_ddagrab_or_desktop_idx(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        probe_config: dict,
    ) -> None:
        """Probe command contains neither '-f ddagrab' nor 'desktop_idx='."""
        captured: list[list[str]] = []
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, *a, **kw: (
                captured.append(cmd)
                or subprocess.CompletedProcess(cmd, 0, b"", b"")
            ),
        )
        monkeypatch.setattr(
            tempfile,
            "NamedTemporaryFile",
            _make_fake_tempfile(tmp_path / "probe.mp4"),
        )

        encoder_probe._try_probe(Path("/ffmpeg"), probe_config)
        assert len(captured) == 1
        as_str = " ".join(captured[0])
        assert "-f ddagrab" not in as_str, "Probe must not use -f ddagrab"
        assert "desktop_idx=" not in as_str, "Probe must not use desktop_idx="

    def test_probe_uses_framerate_in_lavfi(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        probe_config: dict,
    ) -> None:
        """Probe command embeds framerate in lavfi input, not as separate flag."""
        captured: list[list[str]] = []
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, *a, **kw: (
                captured.append(cmd)
                or subprocess.CompletedProcess(cmd, 0, b"", b"")
            ),
        )
        monkeypatch.setattr(
            tempfile,
            "NamedTemporaryFile",
            _make_fake_tempfile(tmp_path / "probe.mp4"),
        )

        encoder_probe._try_probe(Path("/ffmpeg"), probe_config)
        assert len(captured) == 1
        cmd = captured[0]
        i_idx = cmd.index("-i")
        inp = cmd[i_idx + 1]
        assert "framerate=" in inp, (
            f"Probe input must contain framerate=, got: {inp}"
        )
        assert "-framerate" not in cmd, (
            "Probe must not use -framerate flag, use lavfi filter param"
        )

    def test_probe_order_nvenc_qsv_libx264(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """probe_encoder tries h264_nvenc first, then h264_qsv, then libx264.

        Order: NVENC (hardware) → QSV (hardware) → libx264 (software fallback).
        This is the priority defined in the design spec.
        """
        tried: list[str] = []

        def fake_try_probe(ffmpeg_bin: Path, config: dict) -> bool:
            tried.append(config["name"])
            return False  # all fail → probes every encoder

        monkeypatch.setattr(encoder_probe, "_try_probe", fake_try_probe)

        with pytest.raises(SystemExit):
            encoder_probe.probe_encoder(Path("/ffmpeg"), "auto")

        expected = ["h264_nvenc", "h264_qsv", "libx264"]
        assert tried == expected, (
            f"Probe order incorrect. Expected: {expected}, got: {tried}"
        )


class TestDisplayProbeContract:
    """display_probe list_displays_via_ffmpeg and capture_preview must use correct ddagrab."""

    def test_list_displays_uses_lavfi_output_idx(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """list_displays_via_ffmpeg builds commands with -f lavfi and output_idx."""
        captured: list[list[str]] = []

        def mock_run(cmd: list[str], *a: object, **kw: object) -> subprocess.CompletedProcess:
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr(
            tempfile,
            "NamedTemporaryFile",
            _make_fake_tempfile(tmp_path / "display_probe.png"),
        )

        display_probe.list_displays_via_ffmpeg(Path("/ffmpeg"), max_index=1)
        assert len(captured) >= 1, "subprocess.run was not called"
        for cmd in captured:
            as_str = " ".join(cmd)
            assert "-f lavfi" in as_str or cmd[cmd.index("-f") + 1] == "lavfi", (
                f"list_displays must use -f lavfi: {as_str}"
            )
            i_idx = cmd.index("-i")
            inp = cmd[i_idx + 1]
            assert "ddagrab=output_idx=" in inp, (
                f"Input must contain 'ddagrab=output_idx=', got: {inp}"
            )
            assert "desktop_idx=" not in inp, (
                f"Input must not contain 'desktop_idx=', got: {inp}"
            )

    def test_capture_preview_uses_lavfi_output_idx(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """capture_preview builds commands with -f lavfi and output_idx."""
        captured: list[list[str]] = []

        def mock_run(cmd: list[str], *a: object, **kw: object) -> subprocess.CompletedProcess:
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(subprocess, "run", mock_run)

        preview_path = tmp_path / "preview.png"
        display_probe.capture_preview(Path("/ffmpeg"), 0, preview_path)
        assert len(captured) == 1, "subprocess.run was not called"
        cmd = captured[0]
        as_str = " ".join(cmd)
        assert "-f lavfi" in as_str or cmd[cmd.index("-f") + 1] == "lavfi", (
            f"capture_preview must use -f lavfi: {as_str}"
        )
        i_idx = cmd.index("-i")
        inp = cmd[i_idx + 1]
        assert "ddagrab=output_idx=" in inp, (
            f"Input must contain 'ddagrab=output_idx=', got: {inp}"
        )
        assert "desktop_idx=" not in inp, (
            f"Input must not contain 'desktop_idx=', got: {inp}"
        )


# ── D. Temp File Contract ─────────────────────────────────────────────────────


class TestEncoderProbeTempFileContract:
    """Temporary files in encoder_probe._try_probe follow proper lifecycle."""

    def test_temp_file_closed_before_subprocess(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        probe_config: dict,
    ) -> None:
        """Temp file handle is closed BEFORE subprocess.run is called.

        On Windows, an open NamedTemporaryFile cannot be opened by another
        process (FFmpeg).  The handle must be closed — and the underlying
        file released — before spawning the child process.
        """
        events: list[str] = []
        probe_out = tmp_path / "probe_closed.mp4"

        class TrackingTemp:
            name = str(probe_out)

            def close(self) -> None:
                events.append("close")

            def __enter__(self) -> TrackingTemp:
                return self

            def __exit__(self, *a: object) -> None:
                self.close()

        monkeypatch.setattr(
            tempfile, "NamedTemporaryFile", lambda *a, **kw: TrackingTemp()
        )
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, *a, **kw: (
                events.append("subprocess")
                or subprocess.CompletedProcess(cmd, 0, b"", b"")
            ),
        )

        encoder_probe._try_probe(Path("/ffmpeg"), probe_config)

        assert "close" in events, "close() was never called on temp file"
        assert "subprocess" in events, "subprocess.run was never called"
        close_idx = events.index("close")
        subproc_idx = events.index("subprocess")
        assert close_idx < subproc_idx, (
            "Temp file must be closed BEFORE subprocess.run — "
            "FFmpeg cannot write to an open Windows temp file. "
            f"Event order: {events}"
        )

    def test_temp_file_writable_by_mocked_subprocess(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        probe_config: dict,
    ) -> None:
        """When the temp file handle IS closed, the subprocess can write to the path.

        This verifies the design where the temp file is closed before
        subprocess.run, allowing the child process to create/open the file.
        """
        probe_out = tmp_path / "probe_writable.mp4"

        class ClosedTemp:
            """Temp file with handle already closed — mimics correct pattern."""
            name = str(probe_out)

            def close(self) -> None:
                pass  # already closed / never opened in mock

            def __enter__(self) -> ClosedTemp:
                return self

            def __exit__(self, *a: object) -> None:
                self.close()
                # Do NOT delete the file — the test verifies it was created.
                # Real cleanup is tested separately (test_temp_file_cleaned_*).
                pass

        monkeypatch.setattr(
            tempfile, "NamedTemporaryFile", lambda *a, **kw: ClosedTemp()
        )

        def mock_subprocess_run(
            cmd: list[str], *a: object, **kw: object
        ) -> subprocess.CompletedProcess:
            # Simulate the child process writing its output to the temp path
            probe_out.write_text("simulated ffmpeg output", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

        result = encoder_probe._try_probe(Path("/ffmpeg"), probe_config)
        assert result is True, "_try_probe should return True"
        # The file was created by our mock subprocess
        assert probe_out.exists(), (
            "The subprocess must be able to write to the temp file path"
        )
        assert probe_out.read_text(encoding="utf-8") == "simulated ffmpeg output"

    def test_temp_file_cleaned_after_execution(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        probe_config: dict,
    ) -> None:
        """After _try_probe returns, the temp file is cleaned up."""
        probe_out = tmp_path / "probe_cleanup.mp4"
        _was_cleaned: list[bool] = [False]

        class CleanupTemp:
            name = str(probe_out)

            def close(self) -> None:
                pass

            def __enter__(self) -> CleanupTemp:
                return self

            def __exit__(self, *a: object) -> None:
                if probe_out.exists():
                    probe_out.unlink()
                _was_cleaned[0] = True

        monkeypatch.setattr(
            tempfile, "NamedTemporaryFile", lambda *a, **kw: CleanupTemp()
        )
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, *a, **kw: subprocess.CompletedProcess(cmd, 0, b"", b""),
        )

        encoder_probe._try_probe(Path("/ffmpeg"), probe_config)
        assert _was_cleaned[0], "Temp file was not cleaned up after execution"
        assert not probe_out.exists(), "Temp file should be deleted after __exit__"

    def test_display_probe_temp_file_closed_before_subprocess(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """list_displays_via_ffmpeg closes its temp file handle before subprocess.

        Same Windows-handle-lifetime contract as encoder_probe.
        """
        events: list[str] = []
        probe_out = tmp_path / "display_probe_closed.png"

        class TrackingTemp:
            name = str(probe_out)

            def close(self) -> None:
                events.append("close")

            def __enter__(self) -> TrackingTemp:
                return self

            def __exit__(self, *a: object) -> None:
                self.close()

        monkeypatch.setattr(
            tempfile, "NamedTemporaryFile", lambda *a, **kw: TrackingTemp()
        )

        def mock_run(cmd: list[str], *a: object, **kw: object) -> subprocess.CompletedProcess:
            events.append("subprocess")
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(subprocess, "run", mock_run)

        display_probe.list_displays_via_ffmpeg(Path("/ffmpeg"), max_index=1)

        assert "close" in events, "close() was never called"
        assert "subprocess" in events, "subprocess.run was never called"

        close_idx = events.index("close")
        subproc_idx = events.index("subprocess")
        assert close_idx < subproc_idx, (
            "Display probe temp file must be closed before subprocess.run"
        )


# ── E. Config Validation Contract ─────────────────────────────────────────────


class TestConfigValidationContract:
    """supervisor.load_config must reject illegal configuration values."""

    def _write_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict
    ) -> None:
        """Write a config.json to tmp_path and point supervisor.SCRIPT_DIR at it."""
        cfg = {"host_ip": "10.0.0.1", **overrides}
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr(supervisor, "SCRIPT_DIR", tmp_path)

    def test_invalid_host_ip_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-IP host_ip value triggers SystemExit."""
        self._write_config(tmp_path, monkeypatch, {"host_ip": "not-an-ip"})
        with pytest.raises(SystemExit):
            supervisor.load_config()

    def test_negative_display_index_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A negative display_index must be rejected."""
        self._write_config(tmp_path, monkeypatch, {"display_index": -1})
        with pytest.raises(SystemExit):
            supervisor.load_config()

    def test_zero_fps_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fps=0 is invalid (must be >= 1)."""
        self._write_config(tmp_path, monkeypatch, {"fps": 0})
        with pytest.raises(SystemExit):
            supervisor.load_config()

    def test_negative_fps_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative fps is invalid."""
        self._write_config(tmp_path, monkeypatch, {"fps": -30})
        with pytest.raises(SystemExit):
            supervisor.load_config()

    def test_invalid_port_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Port 0 (or out of valid range) must be rejected."""
        self._write_config(tmp_path, monkeypatch, {"rtsp_port": 0})
        with pytest.raises(SystemExit):
            supervisor.load_config()

    def test_out_of_range_port_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Port > 65535 must be rejected."""
        self._write_config(tmp_path, monkeypatch, {"rtsp_port": 99999})
        with pytest.raises(SystemExit):
            supervisor.load_config()

    def test_negative_restart_count_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative max_restarts is invalid."""
        self._write_config(tmp_path, monkeypatch, {"max_restarts": -1})
        with pytest.raises(SystemExit):
            supervisor.load_config()

    def test_unknown_encoder_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An encoder value that is not in the known list must be rejected."""
        self._write_config(tmp_path, monkeypatch, {"encoder": "nonexistent_encoder"})
        with pytest.raises(SystemExit):
            supervisor.load_config()


# ── F. Process Safety Contract ────────────────────────────────────────────────


class TestProcessSafetyContract:
    """All subprocess invocations must be safe (argv, no shell, bounded, no download)."""

    @staticmethod
    def _fake_binary(tmp_path: Path, name: str) -> Path:
        p = tmp_path / name
        p.write_text("fake binary")
        return p

    # ------------------------------------------------------------------
    # subprocess.Popen / .run in supervisor.run_supervisor
    # ------------------------------------------------------------------

    def test_supervisor_popen_uses_argv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """run_supervisor calls subprocess.Popen with argv lists (not shell strings)."""
        popen_cmds: list[tuple[list[str], dict]] = []
        run_cmds: list[tuple[list[str], dict]] = []
        sleep_count: list[int] = [0]

        def track_popen(
            cmd: list[str], *a: object, **kw: object
        ) -> MagicMock:
            popen_cmds.append((cmd, kw))
            m = MagicMock()
            m.pid = 9999
            m.returncode = None
            m.poll.return_value = None
            return m

        def track_run(
            cmd: list[str], *a: object, **kw: object
        ) -> MagicMock:
            run_cmds.append((cmd, kw))
            return MagicMock()

        def count_sleep(_secs: float) -> None:
            sleep_count[0] += 1
            if sleep_count[0] > 3:
                raise KeyboardInterrupt()

        monkeypatch.setattr(subprocess, "Popen", track_popen)
        monkeypatch.setattr(subprocess, "run", track_run)
        monkeypatch.setattr(time, "sleep", count_sleep)
        monkeypatch.setattr(
            encoder_probe, "probe_encoder", lambda *a, **kw: "libx264"
        )
        monkeypatch.setattr(
            supervisor,
            "resolve_binary",
            lambda *a, **kw: self._fake_binary(tmp_path, "fake_binary.exe"),
        )

        # Prepare a minimal runtime environment
        runtime_dir = tmp_path / "runtime"
        cfg = {
            "display_index": 0,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "bitrate": "5M",
            "host_ip": "10.0.0.1",
            "encoder": "auto",
            "ffmpeg_path": "ffmpeg.exe",
            "mediamtx_path": "mediamtx.exe",
            "rtsp_port": 8554,
            "webrtc_http_port": 8889,
            "webrtc_udp_port": 8189,
            "stream_path": "screen",
            "max_restarts": 5,
            "restart_delay_seconds": 3,
            "runtime_dir": str(runtime_dir),
        }
        # Patch SCRIPT_DIR for mediamtx template
        tpl = tmp_path / "mediamtx.template.yml"
        tpl.write_text(MEDIAMTX_TEMPLATE, encoding="utf-8")
        monkeypatch.setattr(supervisor, "SCRIPT_DIR", tmp_path)
        monkeypatch.setattr(supervisor, "PROJECT_ROOT", tmp_path)

        supervisor.run_supervisor(cfg)

        # At least MediaMTX Popen + FFmpeg Popen should have been called
        assert len(popen_cmds) >= 2, (
            "Expected at least 2 Popen calls (MediaMTX + FFmpeg), "
            f"got {len(popen_cmds)}"
        )
        for cmd, kwargs in popen_cmds:
            assert isinstance(cmd, (list, tuple)), (
                f"Popen cmd must be a list/tuple, got {type(cmd).__name__}"
            )
            assert not kwargs.get("shell", False), (
                "shell=True must not be used in Popen"
            )

        # kill_process_tree uses subprocess.run with argv
        for cmd, kwargs in run_cmds:
            assert isinstance(cmd, (list, tuple)), (
                f"subprocess.run cmd must be a list/tuple, got {type(cmd).__name__}"
            )
            assert not kwargs.get("shell", False), (
                "shell=True must not be used in subprocess.run"
            )

    # ------------------------------------------------------------------
    # Encoder probe subprocess.run uses argv
    # ------------------------------------------------------------------

    def test_encoder_probe_uses_argv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, probe_config: dict
    ) -> None:
        """encoder_probe._try_probe calls subprocess.run with argv list, no shell."""
        run_kwargs: list[dict] = []

        def track_run(cmd: list[str], *a: object, **kw: object) -> subprocess.CompletedProcess:
            run_kwargs.append(kw)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(subprocess, "run", track_run)
        monkeypatch.setattr(
            tempfile,
            "NamedTemporaryFile",
            _make_fake_tempfile(tmp_path / "probe_safety.mp4"),
        )

        encoder_probe._try_probe(Path("/ffmpeg"), probe_config)
        assert len(run_kwargs) >= 1, "subprocess.run was not called"
        for kw in run_kwargs:
            assert not kw.get("shell", False), "shell=True must not be used"

    # ------------------------------------------------------------------
    # Display probe subprocess.run uses argv
    # ------------------------------------------------------------------

    def test_display_probe_list_uses_argv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """display_probe.list_displays_via_ffmpeg uses argv, no shell."""
        run_kwargs: list[dict] = []

        def track_run(cmd: list[str], *a: object, **kw: object) -> subprocess.CompletedProcess:
            run_kwargs.append(kw)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(subprocess, "run", track_run)
        monkeypatch.setattr(
            tempfile,
            "NamedTemporaryFile",
            _make_fake_tempfile(tmp_path / "display_safety.png"),
        )

        display_probe.list_displays_via_ffmpeg(Path("/ffmpeg"), max_index=1)
        assert len(run_kwargs) >= 1, "subprocess.run was not called"
        for kw in run_kwargs:
            assert not kw.get("shell", False), "shell=True must not be used"

    # ------------------------------------------------------------------
    # FFmpeg restart bounded by max_restarts (behavioral)
    # ------------------------------------------------------------------

    def test_ffmpeg_restart_bounded_by_max_restarts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """FFmpeg is not started more than 1 + max_restarts times.

        Simulates repeated immediate FFmpeg crashes (poll returns non-None
        on every call) and verifies the supervisor stops restarting after
        max_restarts consecutive failures.
        """
        ffmpeg_starts: list[int] = [0]

        def track_popen(cmd, *a, **kw):
            cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            m = MagicMock()
            m.returncode = None
            m.pid = 9999
            if "mediamtx" in cmd_str.lower():
                m.poll.return_value = None  # stays alive
            elif "ffmpeg" in cmd_str.lower():
                ffmpeg_starts[0] += 1
                m.poll.return_value = 1  # exits immediately
            return m

        monkeypatch.setattr(subprocess, "Popen", track_popen)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(
            encoder_probe, "probe_encoder", lambda *a, **kw: "libx264"
        )
        monkeypatch.setattr(
            supervisor,
            "resolve_binary",
            lambda *a, **kw: self._fake_binary(tmp_path, "fake_binary.exe"),
        )
        tpl = tmp_path / "mediamtx.template.yml"
        tpl.write_text(MEDIAMTX_TEMPLATE, encoding="utf-8")
        monkeypatch.setattr(supervisor, "SCRIPT_DIR", tmp_path)
        monkeypatch.setattr(supervisor, "PROJECT_ROOT", tmp_path)

        runtime_dir = tmp_path / "runtime"
        cfg = {
            "display_index": 0, "width": 1920, "height": 1080,
            "fps": 30, "bitrate": "5M", "host_ip": "10.0.0.1",
            "encoder": "auto", "ffmpeg_path": "ffmpeg.exe",
            "mediamtx_path": "mediamtx.exe",
            "rtsp_port": 8554, "webrtc_http_port": 8889,
            "webrtc_udp_port": 8189, "stream_path": "screen",
            "max_restarts": 5, "restart_delay_seconds": 0,
            "runtime_dir": str(runtime_dir),
        }
        supervisor.run_supervisor(cfg)

        max_expected = 1 + cfg["max_restarts"]
        assert ffmpeg_starts[0] <= max_expected, (
            f"FFmpeg started {ffmpeg_starts[0]} times, "
            f"expected ≤ {max_expected} "
            f"(1 initial + {cfg['max_restarts']} restarts)"
        )

    def test_ffmpeg_restart_count_not_reset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """restart_count must NOT reset after a single healthy poll.

        Bug scenario: FFmpeg runs for one poll cycle (2s), then crashes.
        Each restart is followed by one good cycle, so the counter resets
        every two cycles via the ``else: restart_count = 0`` branch,
        allowing unlimited restarts and bypassing max_restarts.
        """
        ffmpeg_starts: list[int] = [0]

        class RunThenCrashProcess:
            """Survives exactly one poll, then exits."""
            def __init__(self) -> None:
                self.pid = 5000 + ffmpeg_starts[0]
                self.returncode = None
                self._polled = [False]

            def poll(self) -> int | None:
                if not self._polled[0]:
                    self._polled[0] = True
                    return None  # alive on first poll
                self.returncode = 1
                return 1  # crash on second poll

        def track_popen(cmd, *a, **kw):
            cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            if "mediamtx" in cmd_str.lower():
                m = MagicMock()
                m.pid = 1111
                m.poll.return_value = None
                return m
            if "ffmpeg" in cmd_str.lower():
                ffmpeg_starts[0] += 1
                return RunThenCrashProcess()
            return MagicMock()

        monkeypatch.setattr(subprocess, "Popen", track_popen)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock())

        # Safety bound: if the loop never breaks (reset bug), stop after 30 sleeps
        sleep_count: list[int] = [0]

        def bounded_sleep(_secs: float) -> None:
            sleep_count[0] += 1
            if sleep_count[0] > 30:
                raise KeyboardInterrupt()

        monkeypatch.setattr(time, "sleep", bounded_sleep)
        monkeypatch.setattr(
            encoder_probe, "probe_encoder", lambda *a, **kw: "libx264"
        )
        monkeypatch.setattr(
            supervisor,
            "resolve_binary",
            lambda *a, **kw: self._fake_binary(tmp_path, "fake_binary.exe"),
        )
        tpl = tmp_path / "mediamtx.template.yml"
        tpl.write_text(MEDIAMTX_TEMPLATE, encoding="utf-8")
        monkeypatch.setattr(supervisor, "SCRIPT_DIR", tmp_path)
        monkeypatch.setattr(supervisor, "PROJECT_ROOT", tmp_path)

        runtime_dir = tmp_path / "runtime"
        cfg = {
            "display_index": 0, "width": 1920, "height": 1080,
            "fps": 30, "bitrate": "5M", "host_ip": "10.0.0.1",
            "encoder": "auto", "ffmpeg_path": "ffmpeg.exe",
            "mediamtx_path": "mediamtx.exe",
            "rtsp_port": 8554, "webrtc_http_port": 8889,
            "webrtc_udp_port": 8189, "stream_path": "screen",
            "max_restarts": 3, "restart_delay_seconds": 0,
            "runtime_dir": str(runtime_dir),
        }
        supervisor.run_supervisor(cfg)

        max_expected = 1 + cfg["max_restarts"]
        assert ffmpeg_starts[0] <= max_expected, (
            f"FFmpeg started {ffmpeg_starts[0]} times (expected ≤ {max_expected}). "
            f"restart_count resets via the else branch, allowing unlimited "
            f"restarts on a run-then-crash pattern."
        )

    # ------------------------------------------------------------------
    # Missing binary does not download
    # ------------------------------------------------------------------

    def test_missing_binary_no_download(self, tmp_path: Path) -> None:
        """resolve_binary exits on missing binary without downloading anything."""
        with pytest.raises(SystemExit):
            supervisor.resolve_binary(
                "FFmpeg",
                "nonexistent/path/ffmpeg.exe",
            )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fake_tempfile(path: Path):
    """Return a factory that creates a simple mock NamedTemporaryFile-like object.

    The mock has a fixed ``.name`` and does minimal lifecycle tracking.
    """

    class FakeTemp:
        name = str(path)

        def close(self) -> None:
            pass

        def __enter__(self) -> FakeTemp:
            return self

        def __exit__(self, *a: object) -> None:
            pass

    return lambda *a, **kw: FakeTemp()
