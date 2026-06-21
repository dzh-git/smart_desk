/**
 * ScreenView — read-only full-screen stream viewer.
 *
 * Embeds a WebRTC iframe pointing at the central-host MediaMTX relay.
 * The iframe src uses `window.location.hostname` (not a hardcoded IP) so
 * the same code works from any device on the LAN.
 *
 * This page has NO control buttons (no PowerPoint / SolidWorks / SmartDesk
 * switching). Application switching is only allowed from the admin page on
 * the central host itself via the loopback Agent (127.0.0.1:8766).
 */

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Loader2,
  WifiOff,
  MonitorOff,
  AlertCircle,
  RefreshCw,
  Maximize,
} from "lucide-react";
import { fetchHostDisplayStatus } from "../api/resources";
import type { HostDisplayStatus } from "../api/types";

const POLL_INTERVAL_MS = 5_000;

/** Build the WebRTC iframe URL from the current hostname. */
function buildStreamUrl(): string {
  const base = `http://${window.location.hostname}:8889/screen`;
  const params = new URLSearchParams({
    controls: "false",
    muted: "true",
    autoplay: "true",
    playsInline: "true",
  });
  return `${base}?${params.toString()}`;
}

export function ScreenView() {
  const [status, setStatus] = useState<HostDisplayStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [iframeKey, setIframeKey] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const data = await fetchHostDisplayStatus();
      setStatus(data);
      setLoading(false);
      setError(false);
    } catch {
      setError(true);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current != null) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [poll]);

  const handleRetry = () => {
    setIframeKey((k) => k + 1);
    poll();
  };

  const handleFullscreen = () => {
    const el = document.documentElement;
    if (el.requestFullscreen) {
      el.requestFullscreen();
    }
  };

  return (
    <div data-testid="screen-view" className="min-h-screen bg-black flex flex-col">
      {/* Status bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-slate-900 text-white text-xs">
        <div className="flex items-center gap-3">
          {loading && (
            <span data-testid="screen-loading" className="flex items-center gap-1 text-amber-400">
              <Loader2 size={14} className="animate-spin" />
              正在连接…
            </span>
          )}
          {!loading && !error && status && (
            <>
              {status.stream_state === "offline" && (
                <span data-testid="stream-offline" className="flex items-center gap-1 text-red-400">
                  <WifiOff size={14} />
                  流 offline
                </span>
              )}
              {status.agent_state === "offline" && (
                <span data-testid="agent-offline" className="flex items-center gap-1 text-red-400">
                  <MonitorOff size={14} />
                  Agent offline
                </span>
              )}
              {status.active_app && (
                <span
                  data-testid="current-app-name"
                  className="text-slate-300"
                >
                  {status.active_app}
                </span>
              )}
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            data-testid="screen-retry"
            onClick={handleRetry}
            className="p-1 rounded hover:bg-slate-700 transition-colors"
            title="Retry"
          >
            <RefreshCw size={14} />
          </button>
          <button
            data-testid="screen-fullscreen"
            onClick={handleFullscreen}
            className="p-1 rounded hover:bg-slate-700 transition-colors"
            title="Fullscreen"
          >
            <Maximize size={14} />
          </button>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex-1 flex items-center justify-center bg-black">
          <div data-testid="screen-error" className="text-center text-red-400">
            <AlertCircle size={48} className="mx-auto mb-3" />
            <p className="text-sm">无法连接状态服务</p>
          </div>
        </div>
      )}

      {/* Stream iframe */}
      {!error && (
        <div className="flex-1">
          <iframe
            key={iframeKey}
            data-testid="stream-iframe"
            src={buildStreamUrl()}
            className="w-full h-full border-0"
            allow="autoplay; encrypted-media"
            title="Screen Stream"
          />
        </div>
      )}
    </div>
  );
}
