"""
Screen stream supervisor — manages MediaMTX + FFmpeg lifecycle.

Responsibilities:
  - Generate runtime MediaMTX config from template
  - Start MediaMTX, then FFmpeg (ordered)
  - Monitor FFmpeg, restart on crash (limited)
  - Graceful shutdown: kill full process trees
  - Store PID files and logs in runtime directory
  - --check: dry-run validation without starting processes
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── Project root detection ──────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # repo root

# Shared filter chain — single source of truth
from encoder_probe import D3D11_TO_NV12_FILTER


VALID_ENCODERS = {"auto", "h264_nvenc", "h264_qsv", "libx264"}


def load_config() -> dict:
    """Load and validate config.json."""
    config_path = SCRIPT_DIR / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Validate host_ip
    try:
        ipaddress.ip_address(cfg.get("host_ip", ""))
    except ValueError:
        print(f"[ERROR] Invalid host_ip: {cfg.get('host_ip')!r}")
        sys.exit(1)

    # Apply defaults
    cfg.setdefault("display_index", 0)
    cfg.setdefault("width", 1920)
    cfg.setdefault("height", 1080)
    cfg.setdefault("fps", 30)
    cfg.setdefault("bitrate", "5M")
    cfg.setdefault("encoder", "auto")
    cfg.setdefault("ffmpeg_path", "tools/ffmpeg/bin/ffmpeg.exe")
    cfg.setdefault("mediamtx_path", "tools/mediamtx/mediamtx.exe")
    cfg.setdefault("rtsp_port", 8554)
    cfg.setdefault("webrtc_http_port", 8889)
    cfg.setdefault("webrtc_udp_port", 8189)
    cfg.setdefault("stream_path", "screen")
    cfg.setdefault("max_restarts", 5)
    cfg.setdefault("restart_delay_seconds", 3)
    cfg.setdefault("runtime_dir", ".smartdesk-runtime/screen-stream")

    # Validate display_index: must be non-negative integer
    if not isinstance(cfg.get("display_index"), int) or cfg["display_index"] < 0:
        print("[ERROR] display_index must be a non-negative integer")
        sys.exit(1)

    # Validate fps: must be positive
    fps = cfg.get("fps", 30)
    if not isinstance(fps, (int, float)) or fps <= 0:
        print("[ERROR] fps must be a positive number")
        sys.exit(1)

    # Validate ports: must be in 1..65535
    for port_key in ("rtsp_port", "webrtc_http_port", "webrtc_udp_port"):
        port = cfg.get(port_key, 0)
        if not isinstance(port, int) or port <= 0 or port > 65535:
            print(f"[ERROR] {port_key} must be an integer in 1..65535")
            sys.exit(1)

    # Validate max_restarts: must be non-negative
    if not isinstance(cfg.get("max_restarts"), int) or cfg["max_restarts"] < 0:
        print("[ERROR] max_restarts must be a non-negative integer")
        sys.exit(1)

    # Validate encoder: must be one of known values
    if cfg.get("encoder") not in VALID_ENCODERS:
        print(f"[ERROR] encoder must be one of {VALID_ENCODERS}, got {cfg.get('encoder')!r}")
        sys.exit(1)

    return cfg


def resolve_binary(name: str, rel_path: str) -> Path:
    """Resolve a binary path relative to project root; check existence."""
    p = (PROJECT_ROOT / rel_path).resolve()
    if not p.is_file():
        print(f"[ERROR] Binary not found: {name} at {p}")
        sys.exit(1)
    return p


def generate_mediamtx_config(cfg: dict, runtime_dir: Path) -> Path:
    """Generate runtime mediamtx.yml from template, substituting placeholders."""
    template_path = SCRIPT_DIR / "mediamtx.template.yml"
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    replacements = {
        "{{RTSP_PORT}}": str(cfg["rtsp_port"]),
        "{{WEBRTC_HTTP_PORT}}": str(cfg["webrtc_http_port"]),
        "{{WEBRTC_UDP_PORT}}": str(cfg["webrtc_udp_port"]),
        "{{CONTROL_API_PORT}}": "9997",
        "{{METRICS_PORT}}": "9998",
        "{{HOST_IP}}": cfg["host_ip"],
        "{{STREAM_PATH}}": cfg["stream_path"],
    }
    for key, val in replacements.items():
        template = template.replace(key, val)

    out_path = runtime_dir / "mediamtx.yml"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(template)
    return out_path


def build_ffmpeg_command(
    cfg: dict,
    encoder_name: str,
    ffmpeg_bin: Path,
) -> list[str]:
    """Build the FFmpeg argv list for the chosen encoder.

    Uses lavfi ddagrab filter: -f lavfi -i ddagrab=output_idx=N:framerate=M:video_size=WxH
    No shell=True — all args are passed as a list.
    """
    rtsp_url = f"rtsp://127.0.0.1:{cfg['rtsp_port']}/{cfg['stream_path']}"
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    bitrate = cfg["bitrate"]
    lavfi_input = f"ddagrab=output_idx={cfg['display_index']}:framerate={fps}:video_size={w}x{h}"

    if encoder_name == "h264_nvenc":
        return [
            str(ffmpeg_bin),
            "-f", "lavfi",
            "-i", lavfi_input,
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-tune", "ll",
            "-profile:v", "high",
            "-b:v", bitrate,
            "-g", "30",
            "-bf", "0",
            "-pix_fmt", "yuv420p",
            "-an",
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            rtsp_url,
        ]
    elif encoder_name == "h264_qsv":
        return [
            str(ffmpeg_bin),
            "-f", "lavfi",
            "-i", lavfi_input,
            "-c:v", "h264_qsv",
            "-preset", "veryfast",
            "-global_quality", "20",
            "-look_ahead_depth", "0",
            "-g", "30",
            "-bf", "0",
            "-vf", D3D11_TO_NV12_FILTER,
            "-pix_fmt", "nv12",
            "-an",
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            rtsp_url,
        ]
    else:  # libx264 (software fallback)
        return [
            str(ffmpeg_bin),
            "-f", "lavfi",
            "-i", lavfi_input,
            "-vf", D3D11_TO_NV12_FILTER,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-profile:v", "baseline",
            "-b:v", bitrate,
            "-g", "30",
            "-bf", "0",
            "-pix_fmt", "yuv420p",
            "-an",
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            rtsp_url,
        ]


def kill_process_tree(pid: int) -> None:
    """Kill a process and its entire tree on Windows."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def run_supervisor(cfg: dict) -> None:
    """Main supervisor loop: start MediaMTX, start FFmpeg, monitor."""
    runtime_dir = (PROJECT_ROOT / cfg["runtime_dir"])
    runtime_dir.mkdir(parents=True, exist_ok=True)

    # Resolve binaries
    ffmpeg_bin = resolve_binary("FFmpeg", cfg["ffmpeg_path"])
    mediamtx_bin = resolve_binary("MediaMTX", cfg["mediamtx_path"])

    # Generate runtime config
    mediamtx_config = generate_mediamtx_config(cfg, runtime_dir)

    # Determine encoder
    from encoder_probe import probe_encoder
    encoder = cfg.get("encoder", "auto")
    chosen_encoder = probe_encoder(ffmpeg_bin, encoder)
    print(f"[INFO] Using encoder: {chosen_encoder}")

    # Build FFmpeg command
    ffmpeg_cmd = build_ffmpeg_command(cfg, chosen_encoder, ffmpeg_bin)

    # Start MediaMTX
    mediamtx_log = runtime_dir / "mediamtx.log"
    mediamtx_proc = subprocess.Popen(
        [str(mediamtx_bin), str(mediamtx_config)],
        stdout=open(mediamtx_log, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    with open(runtime_dir / "mediamtx.pid", "w") as f:
        f.write(str(mediamtx_proc.pid))
    print(f"[INFO] MediaMTX started (PID {mediamtx_proc.pid})")

    # Wait briefly for MediaMTX to initialize
    time.sleep(2)

    if mediamtx_proc.poll() is not None:
        print("[ERROR] MediaMTX exited immediately")
        sys.exit(1)

    # Start FFmpeg
    ffmpeg_log = runtime_dir / "ffmpeg.log"
    restart_count = 0
    max_restarts = cfg.get("max_restarts", 5)

    def start_ffmpeg():
        return subprocess.Popen(
            ffmpeg_cmd,
            stdout=open(ffmpeg_log, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    ffmpeg_proc = start_ffmpeg()
    with open(runtime_dir / "ffmpeg.pid", "w") as f:
        f.write(str(ffmpeg_proc.pid))
    print(f"[INFO] FFmpeg started (PID {ffmpeg_proc.pid})")

    # Monitor loop
    try:
        while True:
            # Check MediaMTX
            if mediamtx_proc.poll() is not None:
                print("[ERROR] MediaMTX exited unexpectedly")
                break

            # Check FFmpeg
            if ffmpeg_proc.poll() is not None:
                restart_count += 1
                if restart_count > max_restarts:
                    print(f"[ERROR] FFmpeg exited, restart limit ({max_restarts}) reached")
                    break
                delay = cfg.get("restart_delay_seconds", 3)
                print(f"[WARN] FFmpeg exited (rc={ffmpeg_proc.returncode}), "
                      f"restarting in {delay}s ({restart_count}/{max_restarts})")
                time.sleep(delay)
                ffmpeg_proc = start_ffmpeg()
                with open(runtime_dir / "ffmpeg.pid", "w") as f:
                    f.write(str(ffmpeg_proc.pid))
                print(f"[INFO] FFmpeg restarted (PID {ffmpeg_proc.pid})")
            else:
                pass  # healthy — do NOT reset restart_count

            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
    finally:
        # Cleanup
        print("[INFO] Stopping FFmpeg...")
        kill_process_tree(ffmpeg_proc.pid)
        print("[INFO] Stopping MediaMTX...")
        kill_process_tree(mediamtx_proc.pid)
        # Clean PID files
        for pidfile in [runtime_dir / "ffmpeg.pid", runtime_dir / "mediamtx.pid"]:
            pidfile.unlink(missing_ok=True)
        print("[INFO] Shutdown complete")


def main():
    parser = argparse.ArgumentParser(description="SmartDesk Screen Stream Supervisor")
    parser.add_argument("--check", action="store_true",
                        help="Validate config and binaries without starting")
    args = parser.parse_args()

    cfg = load_config()

    if args.check:
        runtime_dir = (PROJECT_ROOT / cfg["runtime_dir"])
        runtime_dir.mkdir(parents=True, exist_ok=True)

        # Check binaries
        resolve_binary("FFmpeg", cfg["ffmpeg_path"])
        resolve_binary("MediaMTX", cfg["mediamtx_path"])

        # Generate config to validate template substitution
        mediamtx_config = generate_mediamtx_config(cfg, runtime_dir)
        print(f"[OK] MediaMTX config generated: {mediamtx_config}")

        # Check encoder
        ffmpeg_bin = resolve_binary("FFmpeg", cfg["ffmpeg_path"])
        from encoder_probe import probe_encoder
        encoder = cfg.get("encoder", "auto")
        chosen = probe_encoder(ffmpeg_bin, encoder)
        print(f"[OK] Encoder selected: {chosen}")

        cmd = build_ffmpeg_command(cfg, chosen, ffmpeg_bin)
        print(f"[OK] FFmpeg command: {' '.join(cmd)}")
        print("[CHECK] All validations passed")
        return

    run_supervisor(cfg)


if __name__ == "__main__":
    main()
