"""
Tests for the screen stream service — config validation, command generation,
encoder selection, and supervisor lifecycle.

All subprocess calls are mocked — these tests do NOT require real FFmpeg
or MediaMTX binaries.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Path setup ──────────────────────────────────────────────────────────────

SCREEN_STREAM_DIR = (
    Path(__file__).resolve().parent.parent / "host_services" / "screen_stream"
)
sys.path.insert(0, str(SCREEN_STREAM_DIR))


# ── Config validation ───────────────────────────────────────────────────────


def test_load_config_returns_defaults(tmp_path, monkeypatch):
    """Config loads and applies defaults."""
    import importlib
    import supervisor

    # Override config path
    config = {
        "host_ip": "10.0.0.1",
        "display_index": 2,
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(supervisor, "SCRIPT_DIR", tmp_path)

    cfg = supervisor.load_config()
    assert cfg["host_ip"] == "10.0.0.1"
    assert cfg["display_index"] == 2
    # Defaults applied
    assert cfg["width"] == 1920
    assert cfg["height"] == 1080
    assert cfg["fps"] == 30
    assert cfg["bitrate"] == "5M"
    assert cfg["rtsp_port"] == 8554
    assert cfg["stream_path"] == "screen"
    assert cfg["max_restarts"] == 5


def test_load_config_invalid_host_ip_exits(tmp_path, monkeypatch, capsys):
    """Invalid host_ip triggers exit."""
    import supervisor

    config = {"host_ip": "not-an-ip"}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(supervisor, "SCRIPT_DIR", tmp_path)

    with pytest.raises(SystemExit):
        supervisor.load_config()


def test_resolve_binary_missing_exits(tmp_path):
    """Missing binary triggers exit."""
    import supervisor

    with pytest.raises(SystemExit):
        supervisor.resolve_binary("FFmpeg", "nonexistent/path/ffmpeg.exe")


# ── MediaMTX config generation ─────────────────────────────────────────────


def test_generate_mediamtx_config_substitutes_placeholders(tmp_path, monkeypatch):
    """Template placeholders are substituted correctly."""
    import supervisor

    # Create template file
    template = """
rtspAddress: :{{RTSP_PORT}}
webrtcAddress: :{{WEBRTC_HTTP_PORT}}
paths:
  {{STREAM_PATH}}:
    webrtcAdditionalHosts: ["{{HOST_IP}}"]
"""
    template_file = tmp_path / "mediamtx.template.yml"
    template_file.write_text(template, encoding="utf-8")
    monkeypatch.setattr(supervisor, "SCRIPT_DIR", tmp_path)

    cfg = {
        "rtsp_port": 8554,
        "webrtc_http_port": 8889,
        "webrtc_udp_port": 8189,
        "host_ip": "192.168.1.50",
        "stream_path": "screen",
    }
    out = supervisor.generate_mediamtx_config(cfg, tmp_path)

    content = out.read_text(encoding="utf-8")
    assert ":8554" in content
    assert ":8889" in content
    assert "192.168.1.50" in content
    assert "screen" in content
    # No unsubstituted placeholders remain
    assert "{{" not in content
    assert "}}" not in content


# ── FFmpeg command generation ───────────────────────────────────────────────


def test_build_ffmpeg_command_nvenc():
    """NVENC command uses correct encoder and args."""
    import supervisor

    cfg = {
        "display_index": 1,
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "bitrate": "8M",
        "rtsp_port": 8554,
        "stream_path": "screen",
    }
    cmd = supervisor.build_ffmpeg_command(cfg, "h264_nvenc", Path("/ffmpeg"))

    assert cmd[0] == str(Path("/ffmpeg"))
    assert "-c:v" in cmd
    nvenc_idx = cmd.index("-c:v")
    assert cmd[nvenc_idx + 1] == "h264_nvenc"
    assert "ddagrab=output_idx=1:framerate=30:video_size=1920x1080" in cmd
    # B-frames disabled
    bf_idx = cmd.index("-bf")
    assert cmd[bf_idx + 1] == "0"
    # GOP 30
    g_idx = cmd.index("-g")
    assert cmd[g_idx + 1] == "30"
    # Bitrate applied
    b_idx = cmd.index("-b:v")
    assert cmd[b_idx + 1] == "8M"
    # No audio
    assert "-an" in cmd
    # RTSP URL
    assert any("rtsp://127.0.0.1:8554/screen" == a for a in cmd)


def test_build_ffmpeg_command_libx264_hwdownload():
    """libx264 software fallback uses the shared D3D11_TO_NV12_FILTER."""
    import supervisor

    cfg = {
        "display_index": 0,
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "bitrate": "5M",
        "rtsp_port": 8554,
        "stream_path": "screen",
    }
    cmd = supervisor.build_ffmpeg_command(cfg, "libx264", Path("/ffmpeg"))

    c_idx = cmd.index("-c:v")
    assert cmd[c_idx + 1] == "libx264"
    # hwdownload filter for D3D11 → CPU frame transfer — uses shared constant
    vf_idx = cmd.index("-vf")
    assert cmd[vf_idx + 1] == supervisor.D3D11_TO_NV12_FILTER
    assert "bgra" in cmd[vf_idx + 1]
    # Baseline profile for software
    p_idx = cmd.index("-profile:v")
    assert cmd[p_idx + 1] == "baseline"


def test_build_ffmpeg_command_qsv():
    """QSV command uses shared D3D11_TO_NV12_FILTER + QuickSync encoder."""
    import supervisor

    cfg = {
        "display_index": 0,
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "bitrate": "5M",
        "rtsp_port": 8554,
        "stream_path": "screen",
    }
    cmd = supervisor.build_ffmpeg_command(cfg, "h264_qsv", Path("/ffmpeg"))

    c_idx = cmd.index("-c:v")
    assert cmd[c_idx + 1] == "h264_qsv"
    # QSV now also uses hwdownload filter for D3D11→NV12 conversion
    vf_idx = cmd.index("-vf")
    assert cmd[vf_idx + 1] == supervisor.D3D11_TO_NV12_FILTER


def test_build_ffmpeg_command_uses_argv_not_shell():
    """FFmpeg command is built as argv list, no shell concatenation."""
    import supervisor

    cfg = {
        "display_index": 0,
        "rtsp_port": 8554,
        "stream_path": "screen",
        "bitrate": "5M",
        "width": 1920,
        "height": 1080,
        "fps": 30,
    }
    cmd = supervisor.build_ffmpeg_command(cfg, "libx264", Path("/ffmpeg"))
    # Should be a list of strings
    assert isinstance(cmd, list)
    assert all(isinstance(a, str) for a in cmd)


def test_d3d11_to_nv12_filter_constant():
    """D3D11_TO_NV12_FILTER has the correct value verified on Intel Graphics."""
    import encoder_probe

    assert encoder_probe.D3D11_TO_NV12_FILTER == "hwdownload,format=bgra,format=nv12"
    # Must contain both the download and the BGRA→NV12 conversion
    assert "hwdownload" in encoder_probe.D3D11_TO_NV12_FILTER
    assert "bgra" in encoder_probe.D3D11_TO_NV12_FILTER
    assert "nv12" in encoder_probe.D3D11_TO_NV12_FILTER


def test_build_ffmpeg_command_nvenc_no_hwdownload():
    """NVENC command must NOT have -vf hwdownload — keeps hardware frames."""
    import supervisor

    cfg = {
        "display_index": 0,
        "rtsp_port": 8554,
        "stream_path": "screen",
        "bitrate": "5M",
        "width": 1920,
        "height": 1080,
        "fps": 30,
    }
    cmd = supervisor.build_ffmpeg_command(cfg, "h264_nvenc", Path("/ffmpeg"))
    assert "-vf" not in cmd, (
        "NVENC must NOT have -vf flag — it keeps D3D11 hardware frames. "
        f"Got: {cmd}"
    )


def test_no_orphaned_hwdownload_format_nv12_in_source():
    """No production source file contains the old broken 'hwdownload,format=nv12'.

    Every occurrence must be part of the corrected 'hwdownload,format=bgra,format=nv12'.
    """
    import encoder_probe
    import supervisor

    OLD = "hwdownload,format=nv12"
    NEW = "hwdownload,format=bgra,format=nv12"

    for label, mod in [("encoder_probe.py", encoder_probe), ("supervisor.py", supervisor)]:
        src = Path(mod.__file__).read_text("utf-8")
        for lineno, line in enumerate(src.splitlines(), 1):
            if OLD in line:
                # The old string may appear inside the NEW string — that's fine
                if NEW in line:
                    continue
                # The constant definition line may mention the old format in a comment
                if "D3D11_TO_NV12_FILTER" in line and "comment" not in label:
                    continue
                pytest.fail(
                    f"{label}:{lineno} contains orphaned '{OLD}' not part of "
                    f"the corrected '{NEW}': {line.strip()}"
                )


# ── Encoder selection ───────────────────────────────────────────────────────


def test_probe_encoder_selects_first_working(monkeypatch):
    """First encoder probe that succeeds is selected."""
    import encoder_probe

    results = {"h264_nvenc": True}

    def fake_try_probe(ffmpeg_bin, config):
        return results.get(config["name"], False)

    monkeypatch.setattr(encoder_probe, "_try_probe", fake_try_probe)
    chosen = encoder_probe.probe_encoder(Path("/ffmpeg"), "auto")
    assert chosen == "h264_nvenc"


def test_probe_encoder_falls_back_to_libx264(monkeypatch):
    """Falls back to libx264 when hardware encoders fail."""
    import encoder_probe

    def fake_try_probe(ffmpeg_bin, config):
        return config["name"] == "libx264"

    monkeypatch.setattr(encoder_probe, "_try_probe", fake_try_probe)
    chosen = encoder_probe.probe_encoder(Path("/ffmpeg"), "auto")
    assert chosen == "libx264"


def test_probe_encoder_preferred_first(monkeypatch):
    """When preferred is set, it's tried first."""
    import encoder_probe

    tried = []

    def fake_try_probe(ffmpeg_bin, config):
        tried.append(config["name"])
        return True  # succeed on first try

    monkeypatch.setattr(encoder_probe, "_try_probe", fake_try_probe)
    chosen = encoder_probe.probe_encoder(Path("/ffmpeg"), "h264_qsv")
    assert chosen == "h264_qsv"
    assert tried[0] == "h264_qsv"


def test_probe_encoder_all_fail_exits(monkeypatch):
    """All encoders failing triggers exit."""
    import encoder_probe

    monkeypatch.setattr(
        encoder_probe, "_try_probe", lambda *a, **kw: False
    )
    with pytest.raises(SystemExit):
        encoder_probe.probe_encoder(Path("/ffmpeg"), "auto")


# ── Supervisor lifecycle (mocked subprocess) ────────────────────────────────


def test_supervisor_check_dry_run(tmp_path, monkeypatch):
    """--check validates binaries and config without starting."""
    import supervisor

    # Create fake binaries
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_text("fake")
    fake_mediamtx = tmp_path / "mediamtx.exe"
    fake_mediamtx.write_text("fake")

    # Create template
    template_file = tmp_path / "mediamtx.template.yml"
    template_file.write_text(
        "rtspAddress: :{{RTSP_PORT}}\npaths:\n  {{STREAM_PATH}}:\n",
        encoding="utf-8",
    )

    cfg = {
        "host_ip": "10.0.0.1",
        "ffmpeg_path": str(fake_ffmpeg),
        "mediamtx_path": str(fake_mediamtx),
        "rtsp_port": 8554,
        "webrtc_http_port": 8889,
        "webrtc_udp_port": 8189,
        "stream_path": "screen",
        "encoder": "libx264",
        "runtime_dir": str(tmp_path / "runtime"),
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

    monkeypatch.setattr(supervisor, "SCRIPT_DIR", tmp_path)
    monkeypatch.setattr(supervisor, "PROJECT_ROOT", tmp_path)

    # Patch encoder probe to skip real FFmpeg
    import encoder_probe
    monkeypatch.setattr(
        encoder_probe, "probe_encoder", lambda *a, **kw: "libx264"
    )

    # Should not raise
    supervisor.main.__wrapped__ if hasattr(
        supervisor.main, "__wrapped__"
    ) else None
    # Call the underlying function with --check
    sys.argv = ["supervisor.py", "--check"]
    # Reload to pick up patched SCRIPT_DIR
    try:
        supervisor.main()
    except SystemExit as e:
        # Should not exit non-zero
        assert e.code == 0 or e.code is None


def test_kill_process_tree_calls_taskkill():
    """kill_process_tree invokes taskkill /T /F."""
    import supervisor

    with patch("supervisor.subprocess.run") as mock_run:
        supervisor.kill_process_tree(12345)
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert "taskkill" in args[0]
        assert "/PID" in args[0]
        assert "12345" in args[0]
        assert "/T" in args[0]
        assert "/F" in args[0]
