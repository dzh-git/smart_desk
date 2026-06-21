"""Display Agent configuration.

Loaded from config.json next to agent.py, with environment variable overrides.
Origin whitelist controls CORS — only SmartDesk local origins are allowed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


class AgentConfig:
    """Agent runtime configuration."""

    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 8766
        # Allowed CORS origins for the local SmartDesk admin page.
        # The browser must serve from one of these local origins.
        self.allowed_origins: list[str] = [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
        # SmartDesk display URL (fixed — not user-supplied)
        self.smartdesk_display_url = "http://127.0.0.1:5173/display"
        # Edge executable candidates (fixed — not user-supplied)
        self.edge_executable_candidates: list[str] = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        # Target display for SolidWorks / PowerPoint slideshow placement.
        # -1 = use primary monitor. The caller must not supply this from the
        # network; only config.json or local admin can change it.
        self.target_display_index = 0
        # Read timeout for the agent's HTTP listener
        self.request_timeout_seconds = 10
        # Whether to attempt COM-based PowerPoint slideshow startup
        self.enable_powerpoint_com = True

    @classmethod
    def load(cls) -> "AgentConfig":
        """Load configuration from config.json with env var overrides.

        Validates host (must be loopback-only) and port (1..65535). Any
        invalid value is rejected and replaced with the safe loopback default.
        """
        cfg = cls()

        config_path = SCRIPT_DIR / "config.json"
        if config_path.is_file():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "host" in data:
                cfg.host = str(data["host"])
            if "port" in data:
                cfg.port = int(data["port"])
            if "allowed_origins" in data and isinstance(
                data["allowed_origins"], list
            ):
                cfg.allowed_origins = [
                    str(o) for o in data["allowed_origins"]
                ]
            if "smartdesk_display_url" in data:
                cfg.smartdesk_display_url = str(
                    data["smartdesk_display_url"]
                )
            if "target_display_index" in data:
                cfg.target_display_index = int(
                    data["target_display_index"]
                )
            if "enable_powerpoint_com" in data:
                cfg.enable_powerpoint_com = bool(
                    data["enable_powerpoint_com"]
                )

        # Environment overrides
        if os.environ.get("DISPLAY_AGENT_PORT"):
            cfg.port = int(os.environ["DISPLAY_AGENT_PORT"])

        # ── Security validation: loopback-only host & valid port range ──
        # The agent must never bind non-loopback interfaces. Any invalid
        # host (empty string, wildcard, LAN IP, IPv6 wildcard) is forced
        # back to the safe loopback default. Port must be in 1..65535.
        if not cls._is_loopback_host(cfg.host):
            print(
                f"[Display Agent] Rejected non-loopback host {cfg.host!r}, "
                f"forcing 127.0.0.1"
            )
            cfg.host = "127.0.0.1"

        if not (isinstance(cfg.port, int) and 0 < cfg.port <= 65535):
            print(
                f"[Display Agent] Rejected invalid port {cfg.port!r}, "
                f"forcing 8766"
            )
            cfg.port = 8766

        return cfg

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        """Return True only for IPv4/IPv6 loopback literals.

        Wildcards (0.0.0.0, ::), empty strings, LAN IPs, and hostnames
        are all rejected. The agent must bind exclusively to loopback.
        """
        if not isinstance(host, str):
            return False
        candidate = host.strip().lower()
        if candidate in ("127.0.0.1", "::1", "localhost"):
            return True
        # Normalize to canonical loopback literals
        if candidate in ("0.0.0.0", "::", "", "[::]"):
            return False
        # Reject any other literal — agent must be explicitly loopback
        return False

    def is_origin_allowed(self, origin: str | None) -> bool:
        """Check whether an Origin header is allowed for CORS."""
        if not origin:
            return False
        return origin in self.allowed_origins


# Module-level singleton, loaded once at startup
CONFIG = AgentConfig.load()
