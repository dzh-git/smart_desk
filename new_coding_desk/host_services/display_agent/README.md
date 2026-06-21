# SmartDesk Display Agent

A user-session-level HTTP service that activates PowerPoint, SolidWorks, or
SmartDesk display windows on the central host. Binds **127.0.0.1:8766 only** —
not accessible from the LAN.

## Architecture

The agent must run in the **logged-in user's interactive desktop session**.
It is NOT a Windows Service — Session 0 isolation prevents Windows Services
from reliably operating PowerPoint, SolidWorks, and browser windows.

Recommended launch methods:
1. Manually via `start_display_agent.bat`
2. A "run at user logon" Scheduled Task that calls `start_display_agent.bat`

## Endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/status` | Read-only summary of running apps + visible windows. |
| `POST` | `/activate` | Switch foreground to powerpoint \| solidworks \| smartdesk. |
| `OPTIONS` | `/status`, `/activate` | CORS preflight. |
| `GET` | `/health` | Liveness probe. |

### `POST /activate` request

```json
{"app": "powerpoint"}
```

`app` must be one of: `powerpoint`, `solidworks`, `smartdesk`.
**Any extra field is rejected** (`extra="forbid"`). No paths, URLs,
commands, or arbitrary strings are accepted.

### Response

```json
{"ok": true, "app": "powerpoint", "action": "activate_slideshow", "detail": ""}
```

## Switch Behavior

| App | Action |
|---|---|
| `powerpoint` | Prefer slideshow window; if none, start slideshow via COM; if COM unavailable, bring editor window forward. |
| `solidworks` | Restore, move to target display, maximize. |
| `smartdesk` | Bring existing `/display` browser window forward; if none, launch Edge in `--app` mode with the **fixed** display URL. |

## Security Properties

- **Loopback only**: binds `127.0.0.1:8766`. Not reachable from LAN.
- **Strict schema**: `ActivateRequest` uses `extra="forbid"` with `Literal` enum.
- **No shell execution**: all `subprocess.Popen` calls use argv arrays.
- **Fixed URL for Edge launch**: the display URL comes from `config.json`, never from the request body.
- **CORS whitelist**: only origins in `allowed_origins` (default `http://127.0.0.1:5173` and `http://localhost:5173`) are accepted.
- **Graceful degradation**: if pywin32 / pythoncom is missing, all Win32 operations return stable error dicts — the agent never crashes.

## Configuration

`config.json` (alongside `agent.py`):

| Field | Default | Notes |
|---|---|---|
| `host` | `127.0.0.1` | Bind host (do not change to 0.0.0.0). |
| `port` | `8766` | Bind port. |
| `allowed_origins` | `["http://127.0.0.1:5173", "http://localhost:5173"]` | CORS whitelist. |
| `smartdesk_display_url` | `http://127.0.0.1:5173/display` | Fixed URL for Edge app launch. |
| `target_display_index` | `0` | Target display for SolidWorks/PPT slideshow placement. |
| `enable_powerpoint_com` | `true` | Enable COM-based slideshow startup. |

## Dependencies

Install in the central host's Python environment:

```powershell
pip install fastapi uvicorn pydantic pywin32 psutil
```

`pywin32` and `psutil` are Windows-only — the agent degrades gracefully
without them, but window operations will report `window_found=false`.

## Operations

```powershell
cd host_services\display_agent
.\start_display_agent.bat
```

Stop:

```powershell
.\stop_display_agent.bat
```

The admin frontend (`http://127.0.0.1:5173/admin`) probes
`http://127.0.0.1:8766/status` and only enables the three switch buttons
when the probe succeeds — which only happens when the browser is running
on the central host itself.
