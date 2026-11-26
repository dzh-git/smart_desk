import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ArrowLeft, ChevronDown, Maximize, RefreshCw } from "lucide-react";
import { fetchHostDisplayStatus } from "../api/resources";
import type { HostDisplayStatus } from "../api/types";
import { SpatialStage } from "../spatial/SpatialStage";
import { ActionButton, StatusBadge, isDemoControlsEnabled } from "./shared";
import "./spectator.css";

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
  const phase = loading ? "busy" : error ? "fault" : showStream ? "live" : "idle";
  return (
    <div data-testid="screen-view" data-spatial-mode="relay" data-spatial-phase={phase} className="spectator spectator-screen">
      <header className="spectator-header">
        <div className="spectator-heading">
          <Link to={returnTo} aria-label="返回 / Back" className="spectator-control spectator-back">
            <ArrowLeft size={18} aria-hidden="true" />
          </Link>
          <div className="min-w-0">
            <h1 className="spectator-meeting-title">中央主机画面</h1>
            <p className="spectator-secondary">Screen Share</p>
          </div>
        </div>
        <div className="spectator-actions">
          {isDemoControlsEnabled() && (
            <StatusBadge status="warning" labelCn="演示模式" labelEn="Demo Mode" />
          )}
          <ActionButton data-testid="screen-retry" className="spectator-control" variant="ghost" size="sm" touch onClick={handleRetry} loading={loading} icon={<RefreshCw size={16} />}>
            刷新 / Retry
          </ActionButton>
          <ActionButton data-testid="screen-fullscreen" className="spectator-control" variant="ghost" size="sm" touch onClick={handleFullscreen} icon={<Maximize size={16} />}>
            全屏 / Fullscreen
          </ActionButton>
          {(status || error || fullscreenError) && (
            <details data-testid="screen-details" className="spectator-screen__details">
              <summary className="spectator-control">播放详情 / Playback Details <ChevronDown size={15} aria-hidden="true" /></summary>
              <div className="spectator-screen__detail-popover">
                {status?.agent_state === "offline" && <p data-testid="agent-offline">Display Agent 离线</p>}
                {status?.active_app && (
                  <p>共享来源 / Source <strong data-testid="current-app-name">{status.active_app}</strong></p>
                )}
                {status && <p>视频流 / Stream <strong>{status.stream_state}</strong></p>}
                {error && <p>{error}</p>}
                {fullscreenError && <p>{fullscreenError}</p>}
              </div>
            </details>
          )}
        </div>
      </header>

      {fullscreenError && <p role="alert" className="spectator-screen__notice">无法进入全屏 / Fullscreen Unavailable</p>}
      {error && showStream && (
        <p role="alert" className="spectator-screen__notice">共享状态更新失败 / Playback Status Unavailable</p>
      )}
      <main className="spectator-screen__main">
        {showStream ? (
          <iframe
            key={iframeKey}
            data-testid="stream-iframe"
            src={buildStreamUrl()}
            className="spectator-screen__video"
            allow="autoplay; encrypted-media"
            title="Screen Stream"
          />
        ) : (
          <>
            <SpatialStage
              className="spectator-stage spectator-screen__stage"
              state={{ mode: "relay", phase, signal: status?.stream_state }}
              showTitle={false}
            />
            <div className="spectator-state spectator-screen__state" role="status">
              {loading ? (
                <h2 data-testid="screen-loading" className="spectator-focus-title">正在连接共享画面…</h2>
              ) : error ? (
                <h2 data-testid="screen-error" className="spectator-focus-title">无法连接共享画面</h2>
              ) : (
                <>
                  <h2 data-testid={status?.stream_state === "offline" ? "stream-offline" : undefined} className="spectator-focus-title">
                    等待中央主机共享
                  </h2>
                  <p className="spectator-secondary">中央主机开始共享后，画面会自动出现。</p>
                  {status?.stream_state === "unknown" && (
                    <ActionButton variant="secondary" touch onClick={() => setTryPlayback(true)}>尝试播放 / Try playback</ActionButton>
                  )}
                </>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
