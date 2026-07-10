/*
 * SmartDesk frontend runtime config.
 *
 * Leave empty for dev / when the frontend is served from the central host
 * (same origin as the backend).
 *
 * On a seat terminal that serves the frontend LOCALLY, edit this file to point
 * at the central host, e.g.:
 *   window.__APP_CONFIG__ = {
 *     apiBase: "http://192.168.1.10:8000",
 *     wsBase:  "ws://192.168.1.10:8000"
 *   };
 */
window.__APP_CONFIG__ = {
  apiBase: "",
  wsBase: ""
};
