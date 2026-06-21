/**
 * Phase 5 — Host Display Control card for /admin Overview workspace.
 *
 * Self-contained component that:
 *  - Reads display status via fetchHostDisplayStatus() (raw JSON, no envelope).
 *  - Probes the loopback Agent at http://127.0.0.1:8766/status to decide
 *    whether the current browser runs on the central host.
 *  - Sends activation requests DIRECTLY to http://127.0.0.1:8766/activate
 *    — NEVER to /api/host-display/activate.
 *  - Does NOT use window.location.hostname for identity checks.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { Loader2, AlertCircle, XCircle } from "lucide-react";
import { fetchHostDisplayStatus } from "../api/resources";
import type { HostDisplayStatus } from "../api/types";
import { SectionCard } from "./shared";

const APPS = [
  { key: "powerpoint", label: "PowerPoint" },
  { key: "solidworks", label: "SolidWorks" },
  { key: "smartdesk", label: "SmartDesk" },
] as const;

type ActivateApp = (typeof APPS)[number]["key"];

/** Minimum shape the loopback Agent /status endpoint returns. */
interface AgentStatusBody {
  agent_state?: string;
}

/** Minimum shape the loopback Agent /activate endpoint returns. */
interface ActivateResponseBody {
  ok?: boolean;
  detail?: string;
  message?: string;
}

const PROBE_TIMEOUT_MS = 3_000;

export function HostDisplayControl() {
  const [status, setStatus] = useState<HostDisplayStatus | null>(null);
  const [agentReachable, setAgentReachable] = useState(false);
  const [activating, setActivating] = useState<ActivateApp | null>(null);
  const [activateError, setActivateError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  // ── Fetch status and probe loopback agent on mount ──────────────────────

  useEffect(() => {
    mountedRef.current = true;

    // Read-only status from the SmartDesk backend (raw JSON, no envelope).
    fetchHostDisplayStatus()
      .then((data) => {
        if (mountedRef.current) setStatus(data);
      })
      .catch(() => {
        /* Backend may be offline — component shows fallback values */
      });

    // Probe the local Agent directly.
    // agent_state === "online" is the definitive signal.
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);

    (async () => {
      try {
        const res = await fetch("http://127.0.0.1:8766/status", {
          signal: controller.signal,
        });
        if (!mountedRef.current) return;
        if (!res.ok) {
          setAgentReachable(false);
          return;
        }
        const body: unknown = await res.json();
        if (mountedRef.current) {
          const agentBody = body as AgentStatusBody;
          setAgentReachable(agentBody.agent_state === "online");
        }
      } catch {
        if (mountedRef.current) setAgentReachable(false);
      }
    })();

    return () => {
      mountedRef.current = false;
      clearTimeout(timeoutId);
      controller.abort();
    };
  }, []);

  // ── App activation — POST directly to loopback Agent ───────────────────

  const handleActivate = useCallback(async (app: ActivateApp) => {
    setActivating(app);
    setActivateError(null);
    try {
      const res = await fetch("http://127.0.0.1:8766/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app }),
      });
      if (!res.ok) {
        const statusCode = res.status;
        let detail = "";
        try {
          const errBody: Record<string, unknown> = await res.json();
          detail = (errBody.detail ?? errBody.message ?? "") as string;
        } catch {
          /* response body not parseable */
        }
        if (statusCode === 409) {
          throw new Error(detail || `App "${app}" is already active (409)`);
        }
        if (statusCode === 503) {
          throw new Error(detail || `Agent temporarily unavailable (503)`);
        }
        // 422, 500, etc.
        throw new Error(detail || `Activation failed (${statusCode})`);
      }

      // HTTP 200 — check body: some agents return {ok: false} with detail.
      try {
        const body: ActivateResponseBody = await res.json();
        if (body.ok === false) {
          throw new Error(body.detail || body.message || `Activation returned ok=false`);
        }
      } catch (err: unknown) {
        // Re-throw only if it's our business-logic error, swallow JSON
        // parse failures (activation still succeeded at HTTP level).
        if (err instanceof Error && !(err instanceof TypeError)) throw err;
      }
    } catch (err: unknown) {
      if (mountedRef.current) {
        if (err instanceof TypeError) {
          setActivateError("Network error — agent unreachable");
        } else if (err instanceof Error) {
          setActivateError(err.message);
        } else {
          setActivateError("Unknown activation error");
        }
      }
    } finally {
      if (mountedRef.current) setActivating(null);
    }
  }, []);

  // ── Derived display values ─────────────────────────────────────────────

  const streamState = status?.stream_state ?? "unknown";
  const agentState = status?.agent_state ?? "offline";
  const activeApp = status?.active_app ?? "—";

  const formatAppState = (key: string): string => {
    const app = status?.apps?.[key];
    if (!app) return "Unknown";
    const parts: string[] = [];
    parts.push(app.running ? "Running" : "Stopped");
    parts.push(app.window_found ? "Window OK" : "No Window");
    return parts.join(" · ");
  };

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <SectionCard title="中央大屏控制" titleEn="HOST DISPLAY">
      <div data-testid="host-display-control" className="space-y-4">
        {/* ── Status row ───────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-xs text-techMuted mb-1">
              流状态 / STREAM STATE
            </p>
            <p
              data-testid="display-stream-state"
              className="text-sm font-semibold text-techText"
            >
              {streamState}
            </p>
          </div>
          <div>
            <p className="text-xs text-techMuted mb-1">
              代理状态 / AGENT STATE
            </p>
            <p
              data-testid="display-agent-state"
              className="text-sm font-semibold text-techText"
            >
              {agentState}
            </p>
          </div>
          <div className="col-span-2">
            <p className="text-xs text-techMuted mb-1">
              当前应用 / ACTIVE APP
            </p>
            <p
              data-testid="display-active-app"
              className="text-sm font-semibold text-techText"
            >
              {activeApp}
            </p>
          </div>
        </div>

        {/* ── App window states ───────────────────────────────────── */}
        <div className="space-y-2 pt-2 border-t border-techBorder">
          <p className="text-xs font-medium text-techMuted">
            窗口状态 / WINDOW STATES
          </p>
          {APPS.map(({ key, label }) => (
            <div
              key={key}
              data-testid={`app-${key}`}
              className="flex items-center justify-between text-xs"
            >
              <span className="text-techText font-medium">{label}</span>
              <span className="text-techMuted">{formatAppState(key)}</span>
            </div>
          ))}
        </div>

        {/* ── Unreachable hint ────────────────────────────────────── */}
        {!agentReachable && (
          <p
            data-testid="local-agent-unreachable"
            className="text-xs text-techMuted bg-techCardSoft rounded px-2 py-1.5 text-center"
          >
            仅中央主机本机可用
          </p>
        )}

        {/* ── Activate buttons ────────────────────────────────────── */}
        <div className="flex flex-wrap gap-2 pt-2 border-t border-techBorder">
          {APPS.map(({ key, label }) => (
            <button
              key={key}
              data-testid={`activate-${key}`}
              disabled={!agentReachable || activating === key}
              onClick={() => handleActivate(key)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                !agentReachable || activating === key
                  ? "opacity-40 cursor-not-allowed bg-techCard border border-techBorder text-techMuted"
                  : "bg-techCyan/20 border border-techCyan/40 text-techCyan hover:bg-techCyan/30 active:bg-techCyan/40"
              }`}
            >
              {activating === key && (
                <Loader2 size={12} className="animate-spin" />
              )}
              {label}
            </button>
          ))}
        </div>

        {/* ── Error display ───────────────────────────────────────── */}
        {activateError && (
          <div
            data-testid="activate-error"
            className="flex items-start gap-2 bg-techRose/10 border border-techRose/30 rounded-lg px-3 py-2"
          >
            <AlertCircle size={12} className="text-techRose shrink-0 mt-0.5" />
            <p className="text-xs text-techRose flex-1">{activateError}</p>
            <button
              onClick={() => setActivateError(null)}
              className="text-techRose/60 hover:text-techRose shrink-0"
              aria-label="Dismiss error"
            >
              <XCircle size={12} />
            </button>
          </div>
        )}
      </div>
    </SectionCard>
  );
}
