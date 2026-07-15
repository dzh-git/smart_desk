"""Small loopback HTTP client for the SmartDesk Display Agent."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import error, request


@dataclass(frozen=True)
class DisplayAgentResult:
    ok: bool
    online: bool
    app: str | None = None
    active_app: str | None = None
    action: str = ""
    detail: str = ""
    status_code: int | None = None


class DisplayAgentClient:
    """Call the local Display Agent without adding a requests dependency."""

    _ALLOWED_APPS = {"powerpoint", "solidworks", "smartdesk"}

    def __init__(self, base_url: str, timeout_seconds: float = 1.5) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def status(self) -> DisplayAgentResult:
        return self._call("GET", "/status")

    def activate(self, app: str) -> DisplayAgentResult:
        if app not in self._ALLOWED_APPS:
            raise ValueError(f"unsupported display app: {app}")
        return self._call("POST", "/activate", {"app": app}, requested_app=app)

    def _call(
        self,
        method: str,
        path: str,
        payload: dict[str, str] | None = None,
        *,
        requested_app: str | None = None,
    ) -> DisplayAgentResult:
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(
            f"{self._base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                data = self._decode_json(response.read())
                return self._result_from_payload(
                    data, int(response.status), requested_app=requested_app
                )
        except error.HTTPError as exc:
            try:
                data = self._decode_json(exc.read())
            except (ValueError, json.JSONDecodeError):
                data = {}
            result = self._result_from_payload(
                data, int(exc.code), requested_app=requested_app
            )
            return DisplayAgentResult(
                ok=False,
                online=True,
                app=result.app,
                active_app=result.active_app,
                action=result.action,
                detail=result.detail or f"Display Agent returned HTTP {exc.code}",
                status_code=int(exc.code),
            )
        except (error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            return DisplayAgentResult(
                ok=False,
                online=False,
                app=requested_app,
                detail=f"Display Agent unavailable: {reason}",
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return DisplayAgentResult(
                ok=False,
                online=True,
                app=requested_app,
                detail=f"Invalid Display Agent response: {exc}",
            )

    @staticmethod
    def _decode_json(body: bytes) -> dict[str, Any]:
        decoded = json.loads(body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("response body is not an object")
        return decoded

    @staticmethod
    def _result_from_payload(
        payload: dict[str, Any],
        status_code: int,
        *,
        requested_app: str | None,
    ) -> DisplayAgentResult:
        is_status = "agent_state" in payload
        ok = payload.get("ok") is True if not is_status else payload.get("agent_state") == "online"
        return DisplayAgentResult(
            ok=ok,
            online=True,
            app=str(payload.get("app") or requested_app) if (payload.get("app") or requested_app) else None,
            active_app=str(payload["active_app"]) if payload.get("active_app") else None,
            action=str(payload.get("action") or ""),
            detail=str(payload.get("detail") or ""),
            status_code=status_code,
        )
