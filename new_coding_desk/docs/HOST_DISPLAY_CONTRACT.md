# SmartDesk Host Display and Screen Stream Contract

This document freezes the interfaces for the central-host screen sharing and
application switching feature. It is normative for Phases 1-6. It describes
both process boundaries and HTTP contracts because the feature spans FFmpeg,
MediaMTX, a loopback Windows agent, the SmartDesk backend, and the frontend.

## 1. Scope and Delivery Status

| Phase | Contract | Code status | Auto-test status | Real-host acceptance |
|---|---|---|---|---|
| 1 | Screen capture, encoding, MediaMTX publishing, and runtime configuration | Implemented | 64 passed (config + phase1) | Intel QSV encoder pre-check: PASS on this host; NVENC pre-check: FAIL (no NVIDIA GPU — expected). Full screen capture, RTSP, WebRTC & multi-terminal acceptance: NOT_RUN |
| 2 | Loopback Windows Display Agent | Implemented | Passed | NOT_RUN |
| 3 | Read-only SmartDesk backend status aggregation | Implemented | Passed | NOT_RUN |
| 4 | `/screen` viewer and `/seat/:seatId` entry | Implemented (raw-json adapter via `apiGetRaw`) | Passed | NOT_RUN |
| 5 | `/admin` local-host application control card | Implemented | Passed | NOT_RUN |
| 6 | Integrated startup, shutdown, deployment configuration, and documentation | Implemented | Passed (launcher contract + phase6) | NOT_RUN |

The status columns are part of the contract. "Implemented" means code is complete
and auto tests pass. Real-host acceptance involves actual FFmpeg ddagrab capture,
MediaMTX WebRTC distribution, Win32/COM switching, firewall, 10-viewer load, and
end-to-end latency measurement — none of which can be certified by mocked tests.

Out of scope:

- file upload, file selection, or document storage;
- remote application switching from another Windows terminal;
- video transport through SmartDesk WebSocket;
- audio streaming;
- database changes;
- Electron migration;
- gesture-control integration.

## 2. Architecture and Trust Boundaries

```text
PowerPoint / SolidWorks / SmartDesk display window
                      |
              Windows target display
                      |
                FFmpeg ddagrab
                      |
       RTSP publish on 127.0.0.1:8554
                      |
                   MediaMTX
                      |
     WebRTC viewer on <central-host>:8889/screen
```

Control and observation are deliberately separate:

- MediaMTX distributes pixels only.
- The Display Agent performs local Win32/COM application switching.
- The SmartDesk backend exposes aggregate status and one Seat 1 authenticated,
  fixed-loopback activation relay.
- `/admin` may call the Display Agent directly only when the browser itself is
  running on the central host.
- In browser code, `127.0.0.1` always means the machine running that browser.
  A remote terminal must therefore see the local Agent as unreachable.
- `POST /api/host-display/activate` requires an enabled device bound to Seat 1,
  a valid device token, and a whitelisted application value. It never accepts
  a caller-supplied target URL.

## 3. Phase 1: Screen Stream Process Contract

### 3.1 Runtime configuration

`host_services/screen_stream/config.json` uses this shape:

```json
{
  "display_index": 0,
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "bitrate": "5M",
  "host_ip": "192.168.1.100",
  "encoder": "auto",
  "ffmpeg_path": "tools/ffmpeg/bin/ffmpeg.exe",
  "mediamtx_path": "tools/mediamtx/mediamtx.exe",
  "rtsp_port": 8554,
  "webrtc_http_port": 8889,
  "webrtc_udp_port": 8189,
  "stream_path": "screen",
  "max_restarts": 5,
  "restart_delay_seconds": 3,
  "runtime_dir": ".smartdesk-runtime/screen-stream"
}
```

Required rules:

- dimensions, FPS, ports, and restart limits must be validated before launch;
- `stream_path` is a single safe path segment and defaults to `screen`;
- `display_index` must be verified with `display_probe.py` on the real host;
- `encoder=auto` probes in order: `h264_nvenc`, `h264_qsv`, then `libx264`;
- encoder availability must be verified by a short real encoding probe, not by
  checking only the FFmpeg encoder list;
- probe temporary files must be created under the configured runtime area and
  cleaned up;
- FFmpeg and MediaMTX binaries are external deployment artifacts and are not
  committed to Git.

Encoder filter contract:

- ddagrab outputs D3D11 frames (GPU memory).
- For libx264 and h264_qsv, a D3D11-to-system-memory conversion is required
  before encoding. This conversion uses the shared filter constant
  `D3D11_TO_NV12_FILTER = "hwdownload,format=bgra,format=nv12"` defined in
  `encoder_probe.py` and imported by `supervisor.py`.
  - `hwdownload`: transfers the D3D11 GPU frame to system memory.
  - `format=bgra`: specifies BGRA as the download target (matches ddagrab's
    native D3D11 pixel format).
  - `format=nv12`: converts BGRA to NV12, the format required by both libx264
    and h264_qsv.
- h264_nvenc encodes the D3D11 frame directly via hardware memory and must NOT
  receive a `-vf` flag — no hwdownload or format conversion is needed.
- The probe (`ENCODER_CONFIGS` in `encoder_probe.py`) and runtime
  (`build_ffmpeg_command()` in `supervisor.py`) use the same
  `D3D11_TO_NV12_FILTER` constant to guarantee filter chain consistency.
- Two frozen tests (`test_no_orphaned_hwdownload_format_nv12_in_source` and
  `test_nvenc_no_hwdownload`) guard against accidental divergence.

### 3.2 Media and network contract

- Capture source: Windows Desktop Duplication through FFmpeg `ddagrab`.
- Output: H.264, `yuv420p`, GOP 30, no B-frames, low-latency settings.
- Publish URL: `rtsp://127.0.0.1:8554/screen` by default.
- RTSP publisher: loopback only, TCP transport.
- WebRTC HTTP viewer: `0.0.0.0:8889`.
- WebRTC ICE UDP mux: `0.0.0.0:8189`.
- MediaMTX Control API: loopback only, default `127.0.0.1:9997`.
- MediaMTX metrics: loopback only, default `127.0.0.1:9998`.
- RTMP, HLS, SRT, recording, and MoQ are disabled in v1.
- Stream path is fixed to `screen`.
- MediaMTX compatibility is pinned to version `1.19.0` for the Control API and
  metrics schema used by Phase 3.

### 3.3 Supervisor contract

- Start MediaMTX before FFmpeg.
- Monitor FFmpeg and restart it no more than `max_restarts` times.
- Delay retries by `restart_delay_seconds`.
- Preserve the last process error for diagnosis.
- On shutdown, terminate owned child processes and do not leave FFmpeg or
  MediaMTX orphaned.

## 4. Phase 2: Windows Display Agent HTTP Contract

The Display Agent is a user-session process, not a Windows Service. It must
bind only to `127.0.0.1:8766` (or another explicit loopback address accepted by
its validated configuration).

### 4.1 `GET /status`

Request:

```http
GET http://127.0.0.1:8766/status
```

Successful response is a raw Agent object, not a SmartDesk response envelope:

```json
{
  "agent_state": "online",
  "win32_available": true,
  "com_available": true,
  "active_app": "powerpoint",
  "apps": {
    "powerpoint": {"running": true, "window_found": true},
    "solidworks": {"running": true, "window_found": true},
    "smartdesk": {"running": true, "window_found": true}
  }
}
```

`active_app` is `powerpoint`, `solidworks`, `smartdesk`, or `null`.

### 4.2 `POST /activate`

```http
POST http://127.0.0.1:8766/activate
Content-Type: application/json

{"app":"powerpoint"}
```

The only accepted values are:

```text
powerpoint
solidworks
smartdesk
```

No extra field is accepted. File paths, URLs, process names, command lines,
arguments, or arbitrary executables are forbidden.

Response schema, including handled failures:

```json
{
  "ok": true,
  "app": "powerpoint",
  "action": "activate_slideshow",
  "detail": ""
}
```

Status rules:

- `200`: request was handled; callers must still inspect `ok` because a Win32
  operation may have produced a partial or unsuccessful result.
- `409`: required application/window is unavailable and cannot be started;
  response body keeps the same `ok/app/action/detail` shape.
- `422`: invalid enum, missing field, or extra field rejected by schema.
- network/CORS failure: the browser treats the Agent as unreachable.

Application behavior:

- PowerPoint prefers an existing slideshow; otherwise it may use COM to start
  the already-open presentation on the configured target display.
- SolidWorks restores, moves, maximizes, and activates an existing
  `SLDWORKS.exe` window.
- SmartDesk activates an existing browser `/display` window or launches a
  fixed configured URL using a fixed Edge executable candidate.

### 4.3 CORS and security

- Origins are an explicit allowlist; wildcard origin is forbidden.
- The allowed origins are exactly `http://127.0.0.1:5173` and
  `http://localhost:5173` (see `host_services/display_agent/config.py`
  `AgentConfig.allowed_origins`).
- `OPTIONS /status` and `OPTIONS /activate` support browser preflight.
- The Agent must not bind to `0.0.0.0` or a LAN address.
- The request cannot influence executable path, URL, or shell arguments.

### 4.4 `GET /health`

A lightweight liveness probe (not part of the frontend/backend data flow):

```http
GET http://127.0.0.1:8766/health
```

Successful response:

```json
{"status": "ok", "agent": "display_agent"}
```

It performs no Win32/FFmpeg work and is used only for process liveness.

## 5. Phase 3: SmartDesk Read-only Status API

### 5.1 `GET /api/host-display/status`

```http
GET /api/host-display/status
```

This endpoint is a deliberate exception to the common SmartDesk response
envelope. The current endpoint returns the following raw object directly:

```json
{
  "agent_state": "online",
  "stream_state": "online",
  "active_app": "powerpoint",
  "viewer_count": 10,
  "apps": {
    "powerpoint": {"running": true, "window_found": true},
    "solidworks": {"running": true, "window_found": true},
    "smartdesk": {"running": true, "window_found": true}
  },
  "profile": {"width": null, "height": null, "fps": null}
}
```

Field contract:

- `agent_state`: `online | offline`.
- `stream_state`: `online | offline | unknown`.
- `active_app`: supported app name or `null`.
- `viewer_count`: non-negative integer or `null`; never fabricate a count.
- `apps`: always contains `powerpoint`, `solidworks`, and `smartdesk`.
- `profile`: always contains `width`, `height`, and `fps`; unavailable values
  are `null`.

Failure behavior:

- Upstream timeout, invalid JSON, non-200 response, or unavailable service must
  not produce a backend 500.
- Agent failure yields `agent_state=offline`, all app flags false, and
  `active_app=null`.
- MediaMTX Control API failure with no usable metrics yields
  `stream_state=unknown`.
- Calls to loopback upstreams use bounded timeouts.

Upstream contract:

- Agent: `http://127.0.0.1:8766/status`.
- MediaMTX Control API: `http://127.0.0.1:9997/v3/paths/list`.
- MediaMTX metrics: `http://127.0.0.1:9998/metrics`.
- Only WebRTC readers for the exact configured stream path contribute to
  `viewer_count`.
- Environment overrides must still resolve to validated loopback HTTP(S) URLs;
  unsafe values fall back to defaults.

The backend must not:

- expose an activate endpoint;
- import or call Win32 APIs;
- run subprocesses;
- write to the database;
- publish a meeting WebSocket event for this feature.

## 6. Phase 4: Frontend Viewer Contract

### 6.0 Response-adapter requirement

The Phase 3 endpoint returns a raw `HostDisplayStatus` object. Since Phase 5,
`fetchHostDisplayStatus()` uses `apiGetRaw()` which reads the body as-is
without expecting an envelope. Test fixtures (vitest + E2E) return raw JSON
matching the actual backend schema. No other API endpoints are affected.

### 6.1 `/screen`

- `/screen` is a read-only route.
- It polls `GET /api/host-display/status` every 5 seconds and clears the timer
  on unmount.
- The WebRTC iframe URL is built from the browser's current hostname:

```text
http://{window.location.hostname}:8889/screen
  ?controls=false
  &muted=true
  &autoplay=true
  &playsInline=true
```

- It displays loading, offline, error, retry, current-app, and fullscreen UI.
- Retry reloads the iframe and refreshes status.
- It does not contain PowerPoint, SolidWorks, or SmartDesk activation controls.
- It does not inspect the cross-origin iframe DOM.

### 6.2 Seat entry

- `/seat/:seatId` provides a visible `共享画面 / Screen Share` entry.
- Activating that entry navigates to `/screen`.
- No video is embedded into the seat workflow itself.
- Existing seat, vote, service, speech, and transcript behavior remains
  unchanged.

## 7. Phase 5: Admin Local Control Contract

Phase 5 is implemented. Key design decisions:

- `fetchHostDisplayStatus()` uses `apiGetRaw()` (not `apiGet()`) to read the
  raw Pydantic response without an envelope wrapper;
- The loopback probe checks `body.agent_state === "online"` (real Agent schema);
- Activate POST parses HTTP-200 body and rejects `{"ok":false}` with `detail`;
- `page.routeWebSocket()` keeps WebSocket alive in E2E (no overlay hack);
- The component is self-contained — no pre-fetch state or mock-pollution guard
  in AdminDashboard.

The default `/admin` Overview workspace contains a Host Display card that:

- reads display state only from `GET /api/host-display/status`;
- separately probes `GET http://127.0.0.1:8766/status` to determine whether
  the browser is running on the central host;
- never uses `window.location.hostname` as a central-host heuristic;
- enables application buttons only after the loopback probe succeeds;
- directly posts to `http://127.0.0.1:8766/activate`;
- desktop `/admin` never posts to `/api/host-display/activate`; the protected
  Android `/host` variant uses that endpoint with Seat 1 device credentials;
- shows stable feedback for 409, 503, CORS, and network failures;
- does not affect meeting controls or other Admin workspaces when it fails.

Required controls:

| Control | Request body |
|---|---|
| PowerPoint | `{"app":"powerpoint"}` |
| SolidWorks | `{"app":"solidworks"}` |
| SmartDesk display | `{"app":"smartdesk"}` |

Remote-host behavior:

- A browser opened on another terminal probes that terminal's own loopback.
- The probe fails unless an Agent happens to be running there.
- All three controls remain disabled and the UI states that control is only
  available on the central host.
- Remote control requires future authentication and an authorized backend
  proxy; it is not part of v1.

## 8. Phase 6: Startup and Deployment Contract

Phase 6 is implemented. Real-host acceptance is NOT_RUN.

### 8.1 `start.bat`

- Backend binds to `127.0.0.1:8000`.
- Vite binds to `0.0.0.0:5173` so LAN terminals can open `/screen`.
- Display Agent starts by default when `ENABLE_DISPLAY_AGENT=true`.
- FFmpeg and MediaMTX screen services start only when `ENABLE_SCREEN_STREAM=true`.
- Display Agent and screen-stream supervisor run in the interactive user
  session, not Session 0.
- Owned process IDs are written under `.smartdesk-runtime`.
- Missing optional screen-stream binaries must produce a clear error without
  silently claiming the stream is online.

### 8.2 `kill.bat`

- Stop owned processes by recorded PID first.
- Clean up Agent and screen-stream supervisor children.
- Ports `8766` and `8889` may be used only as narrowly scoped fallback checks.
- Do not broadly kill every Python, Node, FFmpeg, or MediaMTX process by name.

### 8.3 Repository and deployment files

Git must ignore:

- `tools/ffmpeg/` and `tools/mediamtx/` binaries;
- `.smartdesk-runtime/` PID, log, generated config, and probe output;
- generated screen-stream captures or screenshots.

Expected binary locations:

```text
tools/ffmpeg/bin/ffmpeg.exe
tools/mediamtx/mediamtx.exe
```

Windows firewall exposure:

- TCP 5173: SmartDesk frontend for LAN clients.
- TCP 8889: MediaMTX WebRTC HTTP endpoint.
- UDP 8189: WebRTC media.
- Ports 8000, 8554, 8766, 9997, and 9998 remain loopback-only.

The central host should use a static LAN address or DHCP reservation, and that
address must match `host_ip`/MediaMTX additional-host configuration.

## 9. Frozen Verification Matrix

Existing tests are the executable contract and must not be edited to make an
implementation pass.

| Phase | Frozen verification | Latest result |
|---|---|---|
| 1 | `tests/test_screen_stream_config.py`; `tests/test_screen_stream_phase1_contract.py` | 64 passed |
| 2 | `tests/test_display_agent.py`; `tests/test_display_agent_review_contract.py` | Passed |
| 3 | `tests/test_host_display_api.py`; `tests/test_host_display_review_contract.py` | Passed |
| 4 | `frontend/src/__tests__/screen-view-review.test.tsx`; Playwright `screen-stream-review.spec.ts` filtered by `Phase 4` | Passed |
| 5 | `frontend/src/__tests__/host-display-control-review.test.tsx`; Playwright `screen-stream-review.spec.ts` filtered by `Phase 5` | Passed |
| 6 | `tests/test_screen_stream_phase6_contract.py`; `tests/test_screen_stream_phase6_launch_contract.py`; `tests/test_windows_launcher_contract.py` | Passed |

Required commands:

```powershell
python -m pytest -q tests/test_screen_stream_config.py tests/test_screen_stream_phase1_contract.py
python -m pytest -q tests/test_display_agent.py tests/test_display_agent_review_contract.py
python -m pytest -q tests/test_host_display_api.py tests/test_host_display_review_contract.py
cd frontend
npm test -- --run src/__tests__/screen-view-review.test.tsx
npm test -- --run src/__tests__/host-display-control-review.test.tsx
npx playwright test e2e/screen-stream-review.spec.ts --grep "Phase 4"
npx playwright test e2e/screen-stream-review.spec.ts --grep "Phase 5"
cd ..
python -m pytest -q tests/test_screen_stream_phase6_contract.py tests/test_screen_stream_phase6_launch_contract.py tests/test_windows_launcher_contract.py
```

Encoder pre-check on real hardware:

```powershell
python host_services/screen_stream/supervisor.py --check
```

This command validates config, binary paths, and probes each encoder with a short
real-time capture. On the current Intel Graphics host QSV probe passed and NVENC
failed as expected (no NVIDIA GPU). The result depends on host GPU and driver.
Full RTSP -> MediaMTX -> WebRTC pipeline, multi-display calibration, application
switching, and multi-client load tests cannot be certified by code-level checks.

Real-host acceptance remains mandatory for FFmpeg, MediaMTX, Win32, COM,
PowerPoint, SolidWorks, firewall, 10-viewer load, and end-to-end latency. Mocked
tests cannot certify those hardware-dependent behaviors.

## 10. Change Control

Any change to these items requires updating this contract and the corresponding
frozen tests before implementation:

- ports or network bindings;
- MediaMTX version, API path, or metrics schema;
- stream path or iframe URL construction;
- Agent request/response schemas or app enum;
- backend aggregate response shape;
- local-only control boundary;
- startup ownership and PID-file rules.
