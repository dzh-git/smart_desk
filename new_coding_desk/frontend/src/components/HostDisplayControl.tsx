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
import { DualLabel, SectionCard } from "./shared";

const APPS = [
  { key: "powerpoint", label: "PowerPoint" },
  { key: "solidworks", label: "SolidWorks" },
  { key: "smartdesk", label: "SmartDesk" },
] as const;

type ActivateApp = (typeof APPS)[number]["key"];

interface BilingualCopy {
  cn: string;
  en: string;
}

const STREAM_STATE_COPY: Record<"online" | "offline" | "unknown", BilingualCopy> = {
  online: { cn: "推流正常", en: "STREAM ONLINE" },
  offline: { cn: "未在推流", en: "STREAM OFFLINE" },
  unknown: { cn: "状态未知", en: "STATUS UNKNOWN" },
};

const AGENT_STATE_COPY: Record<"online" | "offline", BilingualCopy> = {
  online: { cn: "控制服务在线", en: "CONTROL SERVICE ONLINE" },
  offline: { cn: "控制服务离线", en: "CONTROL SERVICE OFFLINE" },
};

const APP_NAME_COPY: Record<ActivateApp, BilingualCopy> = {
  powerpoint: { cn: "PowerPoint", en: "POWERPOINT" },
  solidworks: { cn: "SolidWorks", en: "SOLIDWORKS" },
  smartdesk: { cn: "SmartDesk", en: "SMARTDESK" },
};

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

function formatAppState(
  app: HostDisplayStatus["apps"][string] | undefined,
): BilingualCopy {
  if (!app) return { cn: "状态未知", en: "STATUS UNKNOWN" };
  const running = app.running
    ? { cn: "运行中", en: "RUNNING" }
    : { cn: "未运行", en: "STOPPED" };
  const windowState = app.window_found
    ? { cn: "已找到窗口", en: "WINDOW FOUND" }
    : { cn: "未找到窗口", en: "NO WINDOW" };
  return {
    cn: `${running.cn} · ${windowState.cn}`,
    en: `${running.en} · ${windowState.en}`,
  };
}

function formatActiveApp(app: string | null): BilingualCopy {
  if (app && app in APP_NAME_COPY) {
    return APP_NAME_COPY[app as ActivateApp];
  }
  return app
    ? { cn: `其他应用：${app}`, en: "OTHER APP" }
    : { cn: "无", en: "NONE" };
}

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
  const streamCopy = STREAM_STATE_COPY[streamState];
  const agentCopy = AGENT_STATE_COPY[agentState];
  const activeAppCopy = formatActiveApp(status?.active_app ?? null);

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
            <div
              data-testid="display-stream-state"
              className="text-sm"
            >
              <DualLabel cn={streamCopy.cn} en={streamCopy.en} />
            </div>
          </div>
          <div>
            <p className="text-xs text-techMuted mb-1">
              代理状态 / AGENT STATE
            </p>
            <div
              data-testid="display-agent-state"
              className="text-sm"
            >
              <DualLabel cn={agentCopy.cn} en={agentCopy.en} />
            </div>
          </div>
          <div className="col-span-2">
            <p className="text-xs text-techMuted mb-1">
              当前应用 / ACTIVE APP
            </p>
            <div
              data-testid="display-active-app"
              className="text-sm"
            >
              <DualLabel cn={activeAppCopy.cn} en={activeAppCopy.en} />
            </div>
          </div>
        </div>

        {/* ── App window states ───────────────────────────────────── */}
        <div className="space-y-2 pt-2 border-t border-techBorder">
          <p className="text-xs font-medium text-techMuted">
            窗口状态 / WINDOW STATES
          </p>
          {APPS.map(({ key }) => {
            const appCopy = APP_NAME_COPY[key];
            const stateCopy = formatAppState(status?.apps?.[key]);
            return (
            <div
              key={key}
              data-testid={`app-${key}`}
              className="flex items-center justify-between text-xs"
            >
              <DualLabel
                cn={appCopy.cn}
                en={appCopy.en}
                cnClassName="text-xs"
                enClassName="text-[0.55rem]"
              />
              <DualLabel
                cn={stateCopy.cn}
                en={stateCopy.en}
                cnClassName="text-[0.65rem] font-normal text-techMuted"
                enClassName="text-[0.5rem]"
              />
            </div>
            );
          })}
        </div>

        {/* ── Unreachable hint ────────────────────────────────────── */}
        {!agentReachable && (
          <p
            data-testid="local-agent-unreachable"
            className="text-xs text-techMuted bg-techCardSoft rounded px-2 py-1.5 text-center"
          >
            仅可在中央主机操作 / Available on Central Host Only
          </p>
        )}

        {/* ── Activate buttons ────────────────────────────────────── */}
        <div className="flex flex-wrap gap-2 pt-2 border-t border-techBorder">
          {APPS.map(({ key }) => {
            const appCopy = APP_NAME_COPY[key];
            return (
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
              <span>切换至 {appCopy.cn}</span>
              <span className="text-[0.6rem] font-mono uppercase tracking-wider opacity-70">
                Switch to {appCopy.en}
              </span>
            </button>
            );
          })}
        </div>

        {/* ── Error display ───────────────────────────────────────── */}
        {activateError && (
          <div
            data-testid="activate-error"
            className="flex items-start gap-2 bg-techRose/10 border border-techRose/30 rounded-lg px-3 py-2"
          >
            <AlertCircle size={12} className="text-techRose shrink-0 mt-0.5" />
            <p className="text-xs text-techRose flex-1">操作失败 / Operation Failed：{activateError}</p>
            <button
              onClick={() => setActivateError(null)}
              className="text-techRose/60 hover:text-techRose shrink-0"
              aria-label="关闭错误 / Dismiss error"
            >
              <XCircle size={12} />
            </button>
          </div>
        )}
      </div>
    </SectionCard>
  );
}
