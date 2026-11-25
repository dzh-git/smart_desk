import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { AlertCircle, ArrowLeft, Maximize, Monitor, MonitorOff, RefreshCw } from "lucide-react";
import { fetchHostDisplayStatus } from "../api/resources";
import type { HostDisplayStatus } from "../api/types";
import { ActionButton, StatusBadge, isDemoControlsEnabled } from "./shared";

const POLL_INTERVAL_MS = 5000;

function buildStreamUrl() {
  const url = new URL(`http://${window.location.hostname}:8889/screen`);
  url.search = new URLSearchParams({
    controls: "false",
    muted: "true",
    autoplay: "true",
    playsInline: "true",
  }).toString();
  return url.href;
}

export function ScreenView() {
  const location = useLocation();
  const seatId = location.state?.seatId;
  const returnTo = Number.isInteger(seatId) && seatId >= 2 && seatId <= 9
    ? `/seat/${seatId}`
    : "/display";
  const [status, setStatus] = useState<HostDisplayStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fullscreenError, setFullscreenError] = useState<string | null>(null);
  const [tryPlayback, setTryPlayback] = useState(false);
  const [iframeKey, setIframeKey] = useState(0);
  const inFlight = useRef(false);

  const poll = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const nextStatus = await fetchHostDisplayStatus();
      setStatus(nextStatus);
      if (nextStatus.stream_state === "offline") setTryPlayback(false);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法连接状态服务");
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void poll();
    const timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [poll]);

  const handleRetry = () => {
    setLoading(true);
    setIframeKey((current) => current + 1);
    void poll();
  };

  const handleFullscreen = async () => {
    setFullscreenError(null);
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (reason) {
      setFullscreenError(reason instanceof Error ? reason.message : "当前设备无法进入全屏");
    }
  };

  const showStream = status?.stream_state === "online"
    || (status?.stream_state === "unknown" && tryPlayback);
  return (
    <div data-testid="screen-view" className="desk-page flex min-h-dvh flex-col">
      <header className="desk-hero flex flex-wrap items-center justify-between gap-4 border-b border-techBorder px-4 py-4 sm:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <Link to={returnTo} aria-label="返回 / Back" className="mr-2 grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-techBorder text-techMuted hover:text-techText">
            <ArrowLeft size={18} />
          </Link>
          <div className="desk-brand-mark grid h-11 w-11 shrink-0 place-items-center rounded-xl text-techCyan">
            <Monitor size={20} />
          </div>
          <div className="min-w-0">
            <p className="desk-label">SmartDesk · Screen Share</p>
            <h1 className="text-lg font-semibold text-techText sm:text-2xl">中央主机画面</h1>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isDemoControlsEnabled() && (
            <StatusBadge status="warning" labelCn="演示模式" labelEn="Demo Mode" />
          )}
          {status?.agent_state === "offline" && (
            <span data-testid="agent-offline" className="text-xs text-techMuted">Display Agent 离线</span>
          )}
          {status?.active_app && (
            <span data-testid="current-app-name" className="text-sm text-techCyan">{status.active_app}</span>
          )}
          <ActionButton data-testid="screen-retry" variant="secondary" touch onClick={handleRetry} loading={loading} icon={<RefreshCw size={16} />}>
            刷新 / Retry
          </ActionButton>
          <ActionButton data-testid="screen-fullscreen" variant="secondary" touch onClick={handleFullscreen} icon={<Maximize size={16} />}>
            全屏 / Fullscreen
          </ActionButton>
        </div>
      </header>

      {fullscreenError && <p role="alert" className="px-6 pt-3 text-sm text-techAmber">{fullscreenError}</p>}
      {error && showStream && (
        <p role="alert" className="px-6 pt-3 text-sm text-techAmber">共享状态更新失败 · {error}</p>
      )}
      <main className="flex min-h-[18rem] flex-1 flex-col p-4 sm:p-6">
        <div className="desk-panel relative flex min-h-[65vh] flex-1 flex-col overflow-hidden rounded-2xl border border-techBorder bg-techBg">
          {showStream ? (
            <iframe
              key={iframeKey}
              data-testid="stream-iframe"
              src={buildStreamUrl()}
              className="absolute inset-0 h-full w-full border-0 bg-black"
              allow="autoplay; encrypted-media"
              title="Screen Stream"
            />
          ) : (
            <div className="m-auto max-w-lg space-y-3 p-6 text-center" role="status">
              {loading ? (
                <p data-testid="screen-loading" className="text-techCyan">正在连接共享画面…</p>
              ) : error ? (
                <div data-testid="screen-error" className="space-y-2">
                  <AlertCircle size={32} className="mx-auto text-techRose" />
                  <p className="text-lg font-semibold">无法连接状态服务</p>
                  <p className="break-words text-sm text-techMuted">{error}</p>
                </div>
              ) : (
                <>
                  <MonitorOff size={32} className="mx-auto text-techCyan" />
                  <p data-testid={status?.stream_state === "offline" ? "stream-offline" : undefined} className="text-xl font-semibold">
                    等待中央主机共享
                  </p>
                  <p className="text-sm text-techMuted">中央主机开始共享后，画面会自动出现。</p>
                  {status?.stream_state === "unknown" && (
                    <ActionButton variant="secondary" touch onClick={() => setTryPlayback(true)}>尝试播放 / Try playback</ActionButton>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
