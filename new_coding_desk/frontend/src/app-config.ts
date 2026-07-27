/**
 * Runtime configuration injected by /app-config.js (served alongside index.html).
 *
 * - Android WebView => falls back to the configured SmartDeskNative serverUrl.
 * - Empty / absent  => relative URLs. Used in dev (Vite proxy) and when the
 *   frontend is served from the SAME origin as the backend (central host).
 * - Set apiBase/wsBase => the frontend talks to a remote backend. Used when a
 *   seat terminal serves the frontend LOCALLY but must reach the central host.
 *
 * Deploy-time: edit dist/app-config.js on the terminal:
 *   window.__APP_CONFIG__ = { apiBase: "http://192.168.1.10:8000",
 *                             wsBase:  "ws://192.168.1.10:8000" };
 */
type AppConfig = { apiBase?: string; wsBase?: string };
type NativeDeviceEnvelope = {
  type?: string;
  data?: { serverUrl?: string | null };
};

function cfg(): AppConfig {
  const w = window as unknown as { __APP_CONFIG__?: AppConfig };
  return w.__APP_CONFIG__ ?? {};
}

function nativeServerUrl(): string {
  const getDeviceInfo = window.SmartDeskNative?.getDeviceInfo;
  if (typeof getDeviceInfo !== "function") return "";

  try {
    const raw = getDeviceInfo.call(window.SmartDeskNative);
    const envelope = (
      typeof raw === "string" ? JSON.parse(raw) : raw
    ) as NativeDeviceEnvelope;
    return (envelope.data?.serverUrl ?? "").replace(/\/+$/, "");
  } catch {
    return "";
  }
}

/** HTTP API base (no trailing slash). "" => relative "/api/...". */
export function apiBase(): string {
  const explicit = (cfg().apiBase ?? "").replace(/\/+$/, "");
  return explicit || nativeServerUrl();
}

/** WebSocket base (no trailing slash). Falls back to current origin. */
export function wsBase(): string {
  const explicit = (cfg().wsBase ?? "").replace(/\/+$/, "");
  if (explicit) return explicit;
  const nativeBase = nativeServerUrl();
  if (nativeBase) {
    return nativeBase.replace(/^http/i, (scheme) =>
      scheme.toLowerCase() === "https" ? "wss" : "ws",
    );
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}
