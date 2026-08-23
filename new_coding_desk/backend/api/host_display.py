"""
Host display status and authenticated Seat 1 control relay.

Per system_architecture: the backend NEVER calls Win32 and NEVER executes a
shell. Status reads use loopback HTTP only; activation performs a read-only
Seat 1 device-binding check before calling the loopback Display Agent.

Endpoint:
    GET /api/host-display/status

Returns a stable structure even when upstream services are offline.
The desktop browser still calls the loopback Agent directly.  A bound Seat 1
tablet may use POST /api/host-display/activate; the server authenticates the
device and forwards only a whitelisted application name to the fixed loopback
Agent URL.

MediaMTX version contract: this reader targets **MediaMTX 1.19.0**, pinned in
`host_services/screen_stream/README.md`. The Control API path
(`/v3/paths/list`) and the Prometheus metrics schema (`paths_readers{...}` with
`readerType="webrtc"`) correspond to that version. Do not change one without
updating the others and the README pin.
"""

from __future__ import annotations

import logging
import os
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.exceptions import NotFoundError, ValidationError
from backend.schemas import ApiResponse
from backend.services.tablet_device_service import TabletDeviceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/host-display", tags=["host-display"])


# ── Configuration (loopback only — env values are validated & sanitized) ────

# MediaMTX version pinned for the Control API path + metrics schema.
# This must match the version documented in host_services/screen_stream/README.md
MEDIAMTX_VERSION = "1.19.0"


def _validate_loopback_url(raw: str, default: str) -> str:
    """Validate an upstream URL env value.

    Only http(s) URLs pointing at loopback hosts are accepted. Anything else
    (remote hosts, file://, other schemes, empty) falls back to the safe
    loopback default. This prevents SSRF via env-var tampering.
    """
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        parsed = urlparse(raw.strip())
    except Exception:
        return default
    if parsed.scheme not in ("http", "https"):
        return default
    host = (parsed.hostname or "").lower()
    # Accept only loopback / link-local IPv6 loopback
    if host not in ("127.0.0.1", "localhost", "::1"):
        return default
    return raw.strip()


def _sanitize_stream_path(raw: str) -> str:
    """Sanitize the stream path so path-traversal / injection is rejected.

    Only ASCII letters, digits, underscore, dash, and dot are allowed, and the
    result must not contain '..' or path separators. Anything else falls back
    to the default 'screen'.
    """
    if not isinstance(raw, str) or not raw:
        return "screen"
    candidate = raw.strip()
    if not candidate:
        return "screen"
    # Reject path traversal and separators outright
    if ".." in candidate or "/" in candidate or "\\" in candidate:
        return "screen"
    # Reject anything outside the safe charset
    allowed = set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789._-"
    )
    if any(ch not in allowed for ch in candidate):
        return "screen"
    return candidate


AGENT_URL = _validate_loopback_url(
    os.environ.get("SMARTDESK_AGENT_URL", "http://127.0.0.1:8766"),
    "http://127.0.0.1:8766",
)
MEDIAMTX_CONTROL_URL = _validate_loopback_url(
    os.environ.get("SMARTDESK_MEDIAMTX_CONTROL_URL", "http://127.0.0.1:9997"),
    "http://127.0.0.1:9997",
)
MEDIAMTX_METRICS_URL = _validate_loopback_url(
    os.environ.get("SMARTDESK_MEDIAMTX_METRICS_URL", "http://127.0.0.1:9998/metrics"),
    "http://127.0.0.1:9998/metrics",
)

# Conservative timeouts — never hang the API.
HTTP_TIMEOUT_SECONDS = 2.0
STREAM_PATH = _sanitize_stream_path(
    os.environ.get("SMARTDESK_STREAM_PATH", "screen")
)


# ── Response schemas ───────────────────────────────────────────────────────


class AppWindowState(BaseModel):
    running: bool
    window_found: bool


class StreamProfile(BaseModel):
    width: int | None = None
    height: int | None = None
    fps: int | None = None


class HostDisplayStatus(BaseModel):
    agent_state: Literal["online", "offline"]
    stream_state: Literal["online", "offline", "unknown"]
    active_app: str | None = None
    viewer_count: int | None = None
    apps: dict[str, AppWindowState]
    profile: StreamProfile


class HostDisplayActivateRequest(BaseModel):
    deviceId: str
    deviceSeatId: int
    app: str


class HostDisplayActivateResponse(BaseModel):
    app: Literal["powerpoint", "solidworks", "smartdesk"]
    activated: bool = True


def _activate_error(
    status_code: int,
    message: str,
    error_code: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiResponse.fail(message, error_code).model_dump(),
    )


# ── Upstream readers (all use httpx with timeout, never raise) ─────────────


def _read_agent_status() -> dict | None:
    """Read agent status from the loopback Display Agent.

    Returns the JSON dict, or None on any failure (offline / timeout / bad
    JSON). Never raises.
    """
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, trust_env=False) as client:
            resp = client.get(f"{AGENT_URL}/status")
            if resp.status_code != 200:
                return None
            return resp.json()
    except Exception as exc:
        logger.debug("Agent status fetch failed: %s", exc)
        return None


def _read_mediamtx_paths() -> dict | None:
    """Read MediaMTX Control API paths list.

    Uses the `/v3/paths/list` endpoint introduced in MediaMTX 1.18+ (and
    present in the pinned 1.19.0). Returns the JSON dict, or None on failure.
    Never raises.
    """
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, trust_env=False) as client:
            # MediaMTX 1.19.0 Control API path — matches the pinned version.
            resp = client.get(f"{MEDIAMTX_CONTROL_URL}/v3/paths/list")
            if resp.status_code != 200:
                return None
            return resp.json()
    except Exception as exc:
        logger.debug("MediaMTX paths fetch failed: %s", exc)
        return None


def _read_mediamtx_metrics() -> str | None:
    """Read MediaMTX Prometheus metrics as text.

    Returns the metrics text, or None on failure. Never raises.
    """
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, trust_env=False) as client:
            resp = client.get(MEDIAMTX_METRICS_URL)
            if resp.status_code != 200:
                return None
            return resp.text
    except Exception as exc:
        logger.debug("MediaMTX metrics fetch failed: %s", exc)
        return None


def _parse_viewer_count(metrics_text: str | None, stream_path: str) -> int | None:
    """Parse WebRTC viewer count from MediaMTX 1.19.0 Prometheus metrics.

    Targets the `paths_readers` metric emitted by MediaMTX 1.18+, in the form::

        paths_readers{name="<stream_path>",state="ready",readerType="webrtc"} <count>

    Only rows whose `name` matches `stream_path` AND `readerType="webrtc"` are
    counted. Comment lines (`#`), blank lines, and rows with non-numeric
    trailing values are skipped. Returns None when no matching metric is found
    or on any parse ambiguity. Never fabricates a number.
    """
    if not metrics_text:
        return None
    try:
        total = 0
        found_any = False
        # Track exact metric lines to detect duplicates (e.g. from a
        # misconfigured multi-target exporter). Exact duplicates are
        # ambiguous — return None rather than double-counting.
        seen_lines: set[str] = set()
        for line in metrics_text.splitlines():
            stripped = line.strip()
            # Skip comments and blank lines
            if not stripped or stripped.startswith("#"):
                continue
            # Must be the paths_readers metric (1.19.0 schema)
            if "paths_readers" not in stripped:
                continue
            # Must reference the target stream path via name="<path>"
            if f'name="{stream_path}"' not in stripped:
                continue
            # Must be a WebRTC reader — filter by readerType="webrtc" so RTSP
            # and HLS readers are not counted as WebRTC viewers.
            if 'readerType="webrtc"' not in stripped:
                continue
            # Detect exact-duplicate metric lines (ambiguity)
            if stripped in seen_lines:
                return None
            seen_lines.add(stripped)
            # Trailing numeric value: "<metric>{...} <value>"
            parts = stripped.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            try:
                val = float(parts[1])
            except ValueError:
                continue
            total += int(val)
            found_any = True
        if not found_any:
            return None
        return total
    except Exception:
        return None


def _is_stream_online(paths: dict | None, metrics_text: str | None) -> bool | None:
    """Determine whether the stream path is online.

    Returns True if the MediaMTX Control API lists the stream path with a
    ready publisher. Returns False if the Control API responded but the path
    is absent or not ready. Returns None when the Control API is unavailable
    (caller then falls back to metrics-based detection, if any).

    Critically, this does NOT treat the mere presence of the stream-path
    string inside metrics comment/help lines as evidence of being online.
    """
    if not isinstance(paths, dict):
        return None
    items = paths.get("items", [])
    if not isinstance(items, list):
        return False
    for item in items:
        if (
            isinstance(item, dict)
            and item.get("name") == STREAM_PATH
            and item.get("ready", False)
        ):
            return True
    return False


def _parse_stream_profile(
    agent_status: dict | None, paths: dict | None
) -> StreamProfile:
    """Extract stream profile from upstream responses.

    Returns a StreamProfile with None values when unavailable.
    """
    # MediaMTX Control API may expose per-path source information, but the
    # video dimensions come from the publisher. Without a reliable source,
    # we return None values rather than guessing.
    return StreamProfile(width=None, height=None, fps=None)


# ── Endpoint ───────────────────────────────────────────────────────────────


@router.get("/status", response_model=HostDisplayStatus)
def get_host_display_status() -> HostDisplayStatus:
    """Read-only host display status.

    Aggregates Agent + MediaMTX state. Always returns 200 with a stable
    structure. Upstream failures degrade to offline/unknown/null.
    """
    agent_status = _read_agent_status()

    if agent_status is not None:
        agent_state: Literal["online", "offline"] = "online"
        apps_raw = agent_status.get("apps", {})
        apps: dict[str, AppWindowState] = {}
        for app_name in ("powerpoint", "solidworks", "smartdesk"):
            entry = apps_raw.get(app_name, {})
            apps[app_name] = AppWindowState(
                running=bool(entry.get("running", False)),
                window_found=bool(entry.get("window_found", False)),
            )
        active_app = agent_status.get("active_app")
    else:
        agent_state = "offline"
        apps = {
            "powerpoint": AppWindowState(running=False, window_found=False),
            "solidworks": AppWindowState(running=False, window_found=False),
            "smartdesk": AppWindowState(running=False, window_found=False),
        }
        active_app = None

    # MediaMTX stream state — determined by Control API readiness, NOT by
    # naive substring matching against metrics text (which would false-match
    # on comment/help lines that merely contain the stream path name).
    paths = _read_mediamtx_paths()
    metrics_text = _read_mediamtx_metrics()

    stream_state: Literal["online", "offline", "unknown"]
    control_signal = _is_stream_online(paths, metrics_text)
    if control_signal is True:
        stream_state = "online"
    elif control_signal is False:
        # Control API responded but the path is not ready. We may still
        # have evidence from metrics (a real WebRTC reader session), which
        # is a stronger signal than a bare substring match.
        vc = _parse_viewer_count(metrics_text, STREAM_PATH)
        if vc and vc > 0:
            stream_state = "online"
        else:
            stream_state = "offline"
    else:
        # Control API unavailable — fall back to metrics only.
        if metrics_text is None:
            stream_state = "unknown"
        else:
            vc = _parse_viewer_count(metrics_text, STREAM_PATH)
            if vc and vc > 0:
                stream_state = "online"
            else:
                stream_state = "offline"

    viewer_count = _parse_viewer_count(metrics_text, STREAM_PATH)
    profile = _parse_stream_profile(agent_status, paths)

    return HostDisplayStatus(
        agent_state=agent_state,
        stream_state=stream_state,
        active_app=active_app,
        viewer_count=viewer_count,
        apps=apps,
        profile=profile,
    )


@router.post(
    "/activate",
    response_model=ApiResponse[HostDisplayActivateResponse],
)
def activate_host_display(
    payload: HostDisplayActivateRequest,
    token: str | None = Header(None, alias="X-SmartDesk-Device-Token"),
    db: Session = Depends(get_db),
):
    """Activate a host application for the authenticated Seat 1 tablet."""
    if payload.deviceSeatId != 1:
        return _activate_error(
            403,
            "Host display control requires a device bound to Seat 1",
            "HOST_DEVICE_AUTH_FAILED",
        )
    try:
        TabletDeviceService(db).authenticate(
            device_id=payload.deviceId,
            seat_id=1,
            token=token,
        )
    except (NotFoundError, ValidationError):
        logger.warning(
            "Host display activation denied device=%s app=%s",
            payload.deviceId,
            payload.app,
        )
        return _activate_error(
            403,
            "Host tablet authentication failed",
            "HOST_DEVICE_AUTH_FAILED",
        )

    allowed_apps = {"powerpoint", "solidworks", "smartdesk"}
    if payload.app not in allowed_apps:
        return _activate_error(
            422,
            "Unsupported host application",
            "DISPLAY_APP_INVALID",
        )

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, trust_env=False) as client:
            response = client.post(
                f"{AGENT_URL}/activate",
                json={"app": payload.app},
            )
    except httpx.RequestError:
        logger.warning(
            "Host display activation offline device=%s app=%s",
            payload.deviceId,
            payload.app,
        )
        return _activate_error(
            503,
            "Display Agent is offline",
            "DISPLAY_AGENT_OFFLINE",
        )
    except Exception:
        logger.exception(
            "Host display activation failed device=%s app=%s",
            payload.deviceId,
            payload.app,
        )
        return _activate_error(
            502,
            "Display activation failed",
            "DISPLAY_ACTIVATION_FAILED",
        )

    if response.status_code == 409:
        return _activate_error(
            409,
            "Application is already active",
            "DISPLAY_APP_ALREADY_ACTIVE",
        )
    if response.status_code != 200:
        logger.warning(
            "Host display activation rejected device=%s app=%s status=%s",
            payload.deviceId,
            payload.app,
            response.status_code,
        )
        return _activate_error(
            502,
            "Display activation failed",
            "DISPLAY_ACTIVATION_FAILED",
        )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and body.get("ok") is False:
        return _activate_error(
            502,
            "Display activation failed",
            "DISPLAY_ACTIVATION_FAILED",
        )
    logger.info(
        "Host display activation succeeded device=%s app=%s",
        payload.deviceId,
        payload.app,
    )
    return ApiResponse.ok(
        HostDisplayActivateResponse(app=payload.app, activated=True)
    )
