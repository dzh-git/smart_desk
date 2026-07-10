/**
 * Runtime configuration injected by /app-config.js (served alongside index.html).
 *
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

function cfg(): AppConfig {
  const w = window as unknown as { __APP_CONFIG__?: AppConfig };
  return w.__APP_CONFIG__ ?? {};
}

/** HTTP API base (no trailing slash). "" => relative "/api/...". */
export function apiBase(): string {
  return (cfg().apiBase ?? "").replace(/\/+$/, "");
}

/** WebSocket base (no trailing slash). Falls back to current origin. */
export function wsBase(): string {
  const explicit = (cfg().wsBase ?? "").replace(/\/+$/, "");
  if (explicit) return explicit;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}
