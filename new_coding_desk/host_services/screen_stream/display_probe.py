"""
Display probe — lists Windows displays and provides short-time capture preview.

Uses DXGI (via FFmpeg lavfi ddagrab) to enumerate output indices.
Provides short-time capture/screenshot per index for user confirmation.
Writes the confirmed display_index back to config.json.

NOTE: If Windows APIs cannot reliably map DXGI output index to
physical display name, this tool honestly uses "probe per index + confirm"
rather than faking the mapping.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def load_config() -> dict:
    config_path = SCRIPT_DIR / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    config_path = SCRIPT_DIR / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")


def list_displays_via_ffmpeg(ffmpeg_bin: Path, max_index: int = 4) -> list[dict]:
    """Attempt to list available display outputs by probing indices.

    For each index 0..max_index-1, runs a very short FFmpeg lavfi ddagrab capture.
    Indices that succeed are reported as available displays.
    Temp file is closed before subprocess.run to avoid Windows file locking.

    Returns a list of dicts with index and a short FFmpeg info string.
    """
    displays = []

    for idx in range(max_index):
        tmp_path = None
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.close()  # Close BEFORE subprocess.run — Windows file locking
        try:
            cmd = [
                str(ffmpeg_bin),
                "-hide_banner",
                "-loglevel", "error",
                "-f", "lavfi",
                "-i", f"ddagrab=output_idx={idx}:framerate=1",
                "-frames:v", "1",
                "-y",
                tmp_path,
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if proc.returncode == 0:
                    displays.append({
                        "index": idx,
                        "status": "available",
                        "note": "Captured successfully (short probe)",
                    })
                else:
                    stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                    displays.append({
                        "index": idx,
                        "status": "unavailable",
                        "note": stderr[-100:] if stderr else "Capture failed",
                    })
            except subprocess.TimeoutExpired:
                displays.append({
                    "index": idx,
                    "status": "timeout",
                    "note": "Capture timed out",
                })
            except Exception as exc:
                displays.append({
                    "index": idx,
                    "status": "error",
                    "note": str(exc),
                })
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass

    return displays


def capture_preview(ffmpeg_bin: Path, display_index: int, output_path: Path,
                    width: int = 1920, height: int = 1080) -> bool:
    """Capture a preview screenshot from a specific display index.

    Uses lavfi ddagrab format.
    Saves to output_path. Returns True on success.
    """
    cmd = [
        str(ffmpeg_bin),
        "-hide_banner",
        "-f", "lavfi",
        "-i", f"ddagrab=output_idx={display_index}:framerate=1:video_size={width}x{height}",
        "-frames:v", "1",
        "-y",
        str(output_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return proc.returncode == 0
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="SmartDesk Display Probe — list and calibrate target display",
    )
    parser.add_argument(
        "--ffmpeg", type=str, default=None,
        help="Path to ffmpeg.exe (default: from config.json)",
    )
    parser.add_argument(
        "--max-index", type=int, default=4,
        help="Maximum display index to probe (default: 4)",
    )
    parser.add_argument(
        "--set", type=int, default=None,
        help="Set display_index in config.json without interactive prompt",
    )
    parser.add_argument(
        "--capture", type=int, default=None,
        help="Capture a preview screenshot from the given index",
    )
    args = parser.parse_args()

    cfg = load_config()

    ffmpeg_rel = args.ffmpeg or cfg.get("ffmpeg_path", "tools/ffmpeg/bin/ffmpeg.exe")
    ffmpeg_bin = (SCRIPT_DIR.parent.parent / ffmpeg_rel).resolve()
    if not ffmpeg_bin.is_file():
        print(f"[ERROR] FFmpeg not found: {ffmpeg_bin}")
        sys.exit(1)

    # Direct set mode
    if args.set is not None:
        cfg["display_index"] = args.set
        save_config(cfg)
        print(f"[OK] display_index set to {args.set} in config.json")
        return

    # Capture preview mode
    if args.capture is not None:
        runtime_dir = SCRIPT_DIR.parent.parent / cfg.get(
            "runtime_dir", ".smartdesk-runtime/screen-stream"
        )
        runtime_dir.mkdir(parents=True, exist_ok=True)
        preview_path = runtime_dir / f"display_preview_{args.capture}.png"
        if capture_preview(ffmpeg_bin, args.capture, preview_path):
            print(f"[OK] Preview saved: {preview_path}")
        else:
            print(f"[FAIL] Could not capture display index {args.capture}")
        return

    # List mode — enumerate available displays
    print("Probing display outputs via FFmpeg lavfi ddagrab...")
    print(f"FFmpeg: {ffmpeg_bin}")
    print()

    displays = list_displays_via_ffmpeg(ffmpeg_bin, args.max_index)

    available = [d for d in displays if d["status"] == "available"]
    if not available:
        print("[ERROR] No available displays found via ddagrab probe.")
        print("Check that FFmpeg supports ddagrab and a desktop session is active.")
        sys.exit(1)

    print("Available displays:")
    for d in available:
        marker = " <-- current" if d["index"] == cfg.get("display_index", 0) else ""
        print(f"  Index {d['index']}: {d['note']}{marker}")

    print()
    print(f"Current config display_index: {cfg.get('display_index', 0)}")
    print()
    print("To set the target display index, run:")
    print(f"  python display_probe.py --set <index>")
    print("To capture a preview screenshot, run:")
    print(f"  python display_probe.py --capture <index>")


if __name__ == "__main__":
    main()
