"""
Encoder probe — attempts real short-time encoding probes for each encoder.

Priority order: h264_nvenc → h264_qsv → libx264

Each probe runs a very short FFmpeg capture (2 seconds, 30 frames)
using lavfi ddagrab. The probe that succeeds first is selected.
All probes use argv arrays, never shell=True.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


# ── Shared filter chain constant ──────────────────────────────────────────────
# Verified working on Intel Graphics (2026-06-19):
#   ddagrab outputs D3D11 wrapped_avframe → hwdownload to BGRA → format to NV12
D3D11_TO_NV12_FILTER = "hwdownload,format=bgra,format=nv12"


# Encoder configurations with distinct filter chains
ENCODER_CONFIGS = [
    {
        "name": "h264_nvenc",
        "requires_hw": True,
        "extra_args": [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-tune", "ll",
            "-profile:v", "high",
            "-b:v", "5M",
            "-g", "30",
            "-bf", "0",
            "-pix_fmt", "yuv420p",
        ],
    },
    {
        "name": "h264_qsv",
        "requires_hw": True,
        "extra_args": [
            "-c:v", "h264_qsv",
            "-preset", "veryfast",
            "-global_quality", "20",
            "-look_ahead_depth", "0",
            "-g", "30",
            "-bf", "0",
            "-vf", D3D11_TO_NV12_FILTER,
            "-pix_fmt", "nv12",
        ],
    },
    {
        "name": "libx264",
        "requires_hw": False,
        "extra_args": [
            "-vf", D3D11_TO_NV12_FILTER,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-profile:v", "baseline",
            "-b:v", "5M",
            "-g", "30",
            "-bf", "0",
            "-pix_fmt", "yuv420p",
        ],
    },
]


def probe_encoder(ffmpeg_bin: Path, preferred: str = "auto") -> str:
    """Probe encoders in priority order and return the first that works.

    If preferred is "auto" (default), probes in order: nvenc → qsv → libx264.
    If preferred is a specific encoder name, probes only that one, then
    falls back to libx264 if it fails.

    All probes use subprocess, no shell=True.
    """
    if preferred == "auto":
        order = [e["name"] for e in ENCODER_CONFIGS]
    else:
        # Put preferred first, then others in default order, then libx264 last
        order = [preferred]
        for e in ENCODER_CONFIGS:
            if e["name"] != preferred and e["name"] not in order:
                order.append(e["name"])
        if "libx264" not in order:
            order.append("libx264")

    for enc_name in order:
        config = next((e for e in ENCODER_CONFIGS if e["name"] == enc_name), None)
        if config is None:
            print(f"[WARN] Unknown encoder: {enc_name}")
            continue

        result = _try_probe(ffmpeg_bin, config)
        if result:
            return enc_name

    print("[ERROR] No working encoder found")
    sys.exit(1)


def _try_probe(ffmpeg_bin: Path, config: dict) -> bool:
    """Attempt a single short-time encoding probe.

    Captures 30 frames from output_idx=0 using lavfi ddagrab.
    Outputs to a temp null file (discarded).
    Temp file handle is closed BEFORE subprocess.run (Windows file locking).
    Cleanup is handled by the NamedTemporaryFile context manager __exit__.

    Returns True if FFmpeg exits with code 0 within timeout.
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        tmp.close()  # Release handle BEFORE subprocess.run — Windows file locking
        tmp_path = tmp.name
        cmd = [
            str(ffmpeg_bin),
            "-hide_banner",
            "-loglevel", "warning",
            "-f", "lavfi",
            "-i", "ddagrab=output_idx=0:framerate=30",
            "-frames:v", "30",
            "-an",
            *config["extra_args"],
            "-y",
            tmp_path,
        ]

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if proc.returncode == 0:
                print(f"[OK] Probe succeeded: {config['name']}")
                return True
            else:
                stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                print(f"[FAIL] Probe {config['name']}: exit code {proc.returncode}")
                lines = stderr.split("\n")
                for line in lines[-2:]:
                    if line.strip():
                        print(f"       {line.strip()}")
                return False
        except subprocess.TimeoutExpired:
            print(f"[FAIL] Probe {config['name']}: timed out")
            return False
        except FileNotFoundError:
            print(f"[ERROR] FFmpeg not found: {ffmpeg_bin}")
            sys.exit(1)
        except Exception as exc:
            print(f"[FAIL] Probe {config['name']}: {exc}")
            return False


if __name__ == "__main__":
    """Standalone encoder probe for manual testing."""
    if len(sys.argv) < 2:
        print("Usage: python encoder_probe.py <path_to_ffmpeg.exe> [preferred_encoder]")
        sys.exit(1)

    ffmpeg_path = Path(sys.argv[1])
    preferred = sys.argv[2] if len(sys.argv) > 2 else "auto"
    chosen = probe_encoder(ffmpeg_path, preferred)
    print(f"\nSelected encoder: {chosen}")
