# SmartDesk Screen Stream Service

Captures a target Windows display via FFmpeg `ddagrab`, publishes H.264 over
RTSP to MediaMTX, which then distributes to browser viewers over WebRTC.

```text
中央主机目标显示器
  → FFmpeg ddagrab (D3D11)
  → RTSP 127.0.0.1:8554/screen
  → MediaMTX
  → WebRTC http://中央主机IP:8889/screen
  → 10 个终端浏览器 /screen
```

## Binaries

Binaries are NOT committed to git. Place them at the fixed paths below:

| Binary | Required Path |
|---|---|
| FFmpeg | `tools/ffmpeg/bin/ffmpeg.exe` |
| MediaMTX | `tools/mediamtx/mediamtx.exe` |

FFmpeg must support `ddagrab` (FFmpeg 6.1+ on Windows).
MediaMTX version: pinned to **MediaMTX 1.19.0**. The Control API path
(`/v3/paths/list`) and Prometheus metrics schema (`paths_readers{...}`) in
this documentation and in the backend status reader target this exact
version. Do not substitute a different MediaMTX version without re-validating
the Control API path and metrics schema against that version's documentation.
**待实机验证**: this configuration has not been validated against a specific
MediaMTX binary on a real host. Verify the generated `mediamtx.yml` matches
your installed version before production use.

## Configuration

`config.json` controls capture parameters:

| Field | Default | Notes |
|---|---|---|
| `display_index` | `0` | DXGI output index. Run `display_probe.py` to calibrate. |
| `width` | `1920` | Capture width. |
| `height` | `1080` | Capture height. |
| `fps` | `30` | Capture framerate. |
| `bitrate` | `5M` | H.264 bitrate. Increase to `8-12M` for SolidWorks. |
| `host_ip` | `192.168.1.100` | Central host LAN IP. Validated as a real IP address. |
| `encoder` | `auto` | `auto` probes NVENC → QSV → libx264. |
| `ffmpeg_path` | `tools/ffmpeg/bin/ffmpeg.exe` | Relative to repo root. |
| `mediamtx_path` | `tools/mediamtx/mediamtx.exe` | Relative to repo root. |
| `rtsp_port` | `8554` | RTSP publish port (loopback only). |
| `webrtc_http_port` | `8889` | WebRTC HTTP port (LAN accessible). |
| `webrtc_udp_port` | `8189` | WebRTC UDP/ICE port (LAN accessible). |
| `stream_path` | `screen` | Fixed MediaMTX path. |
| `max_restarts` | `5` | FFmpeg auto-restart limit. |
| `restart_delay_seconds` | `3` | Delay between FFmpeg restarts. |

MediaMTX runtime config is generated from `mediamtx.template.yml` into
`.smartdesk-runtime/screen-stream/mediamtx.yml` at startup. Do not edit the
runtime file directly; edit the template or `config.json`.

## Encoder Selection

The supervisor probes each encoder with a real short-time capture, in order:

1. **h264_nvenc** — NVIDIA hardware encoder (encodes D3D11 frames directly, no `-vf` flag)
2. **h264_qsv** — Intel QuickSync encoder (uses `hwdownload,format=bgra,format=nv12` to convert D3D11 frames)
3. **libx264** — software fallback (uses the same filter as QSV)

Only the first encoder that successfully captures 30 frames is used. The probe
runs FFmpeg with `argv` arrays (no `shell=True`) and validates return code.

The D3D11-to-system-memory conversion filter is defined as the shared constant
`D3D11_TO_NV12_FILTER = "hwdownload,format=bgra,format=nv12"` in
`encoder_probe.py` and imported by `supervisor.py`. Both probe (`ENCODER_CONFIGS`)
and runtime (`build_ffmpeg_command()`) use the identical constant, guaranteeing
that the filter chain tested during `--check` matches the one used at runtime.
NVENC encodes the D3D11 frame in GPU memory and must NOT receive a `-vf` flag.
Two frozen tests guard against accidental filter divergence.

## Display Calibration

```powershell
cd host_services\screen_stream
python display_probe.py
```

Lists available displays (indices 0..3 by default) and confirms which respond
to `ddagrab`. To set the target:

```powershell
python display_probe.py --set 1
python display_probe.py --capture 1   # saves preview PNG to runtime dir
```

**Important**: DXGI `output_idx` does not reliably map to Windows display
names after display hotplug or driver changes. Re-run the probe whenever the
display layout changes.

## Operations

Dry-run validation (does not start processes):

```powershell
cd host_services\screen_stream
python supervisor.py --check
```

This command validates config, binary paths, and runs a short real encoding probe
for each available encoder. On the current Intel Graphics host QSV passed and
NVENC failed as expected (no NVIDIA GPU). **Note:** `--check` only validates the
encoder; it does not start MediaMTX, publish RTSP, or verify WebRTC playback.

Start the supervisor (foreground, current user session):

```powershell
.\start_screen_stream.bat
```

Stop:

```powershell
.\stop_screen_stream.bat
```

PID files, logs, and generated config live in
`.smartdesk-runtime/screen-stream/`.

## Verification Status

| Check | Status |
|---|---|
| Auto tests (`test_screen_stream_config.py` + `phase1_contract.py`) | 64 passed |
| Auto tests (Phase 2-6, launcher contract) | Passed |
| Intel QSV `--check` on this host | PASS |
| NVENC `--check` on this host | FAIL (no NVIDIA GPU — expected) |
| Full RTSP -> MediaMTX -> WebRTC pipeline | NOT_RUN |
| Multi-display calibration | NOT_RUN |
| Application switching (PowerPoint, SolidWorks) | NOT_RUN |
| 10-client concurrency | NOT_RUN |
| 60-minute stability | NOT_RUN |
| FFmpeg auto-restart on crash | NOT_RUN |

## Network Bindings

| Service | Bind | Access |
|---|---|---|
| RTSP publish | `127.0.0.1:8554` | loopback only |
| WebRTC HTTP | `0.0.0.0:8889` | LAN |
| WebRTC UDP/ICE | `0.0.0.0:8189` | LAN |
| Control API | `127.0.0.1:9997` | loopback only |
| Metrics | `127.0.0.1:9998` | loopback only |

RTMP, HLS, SRT, and MoQ are disabled in the first version.

## Security Notes

- `host_ip` is validated via Python `ipaddress` before substitution into the
  MediaMTX template. No raw YAML/JSON injection is possible.
- All subprocess calls use argv arrays; no `shell=True`.
- No network services bind to a public interface except WebRTC HTTP/UDP, which
  is required for LAN viewers.
- FFmpeg and MediaMTX binaries are loaded from fixed paths; the supervisor does
  not accept user-supplied binary paths at runtime.
