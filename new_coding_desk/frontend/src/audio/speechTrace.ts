/**
 * SpeechTrace — minimal diagnostic instrumentation for speech pipeline audit.
 *
 * This is a TEMPORARY diagnostic module. It is NOT a product feature.
 * It records timestamped trace events in a ring buffer scoped to the module.
 * Traces include utterance_id, meeting_id, seat_id, and revision for correlation.
 *
 * ## DEFAULT OFF
 * Tracing is DISABLED by default. Enable with the environment variable:
 *   VITE_ENABLE_SPEECH_TRACE=true
 * When disabled, trace() is a no-op and the ring buffer stays empty.
 *
 * ## Ring buffer
 * The buffer holds at most MAX_ENTRIES events. When full, the oldest event
 * is discarded. This prevents unbounded memory growth during long meetings.
 *
 * Usage:
 *   import { trace, getTrace, clearTrace } from "../audio/speechTrace";
 *   trace("frontend_pcm_created_at", { utteranceId: "utt_1_1_000001" });
 *
 * No data is persisted, no API endpoint exposes it. Only for Task 125 audit.
 */

const MAX_ENTRIES = 1000;

/** True when VITE_ENABLE_SPEECH_TRACE is set to "true". */
const _enabled: boolean =
  (typeof import.meta !== "undefined" &&
    import.meta.env?.VITE_ENABLE_SPEECH_TRACE === "true") ||
  false;

export interface TraceEvent {
  event: string;
  timestamp: number; // performance.now() relative time
  data: Record<string, unknown>;
}

const _traceBuffer: TraceEvent[] = [];

/** Record a trace event with optional data. No-op when tracing is disabled. */
export function trace(
  event: string,
  data: Record<string, unknown> = {},
): void {
  if (!_enabled) return;

  _traceBuffer.push({
    event,
    timestamp: performance.now(),
    data,
  });

  // Ring buffer: discard oldest when over capacity
  if (_traceBuffer.length > MAX_ENTRIES) {
    _traceBuffer.shift();
  }
}

/** Return a copy of all recorded trace events. */
export function getTrace(): TraceEvent[] {
  return [..._traceBuffer];
}

/** Clear all recorded trace events. Safe to call multiple times. */
export function clearTrace(): void {
  _traceBuffer.length = 0;
}

/** True when speech tracing is enabled via VITE_ENABLE_SPEECH_TRACE. */
export function isTraceEnabled(): boolean {
  return _enabled;
}

// ── Console / file export helpers (Task 128A rework) ──────────────────────

/**
 * Export the current trace buffer as a JSON-serializable object.
 *
 * The result includes all recorded events plus metadata (recorded_at,
 * event_count, trace_enabled) and a wall_clock_offset_ms field that
 * bridges the gap between performance.now() and Date.now() so the
 * backend latency report can align frontend and backend timestamps.
 *
 * wall_clock_offset_ms = Date.now() - performance.now()
 *   Capture this at export time. For any trace event with frontend
 *   timestamp T (performance.now), its estimated wall-clock time is:
 *     wall_clock_offset_ms + T
 *
 * Use from the browser DevTools console:
 *   copy(JSON.stringify(window.__SMARTDESK_SPEECH_TRACE__, null, 2))
 *
 * Or call downloadTraceFile() to trigger a file download.
 */
export function getTraceReport(): {
  recorded_at: string;
  trace_enabled: boolean;
  event_count: number;
  wall_clock_offset_ms: number;
  events: TraceEvent[];
} {
  const now = Date.now();
  const perfNow = performance.now();
  return {
    recorded_at: new Date().toISOString(),
    trace_enabled: _enabled,
    event_count: _traceBuffer.length,
    wall_clock_offset_ms: Math.round(now - perfNow),
    events: [..._traceBuffer],
  };
}

/**
 * Serialize the trace buffer to a JSON string.
 */
export function serializeTrace(): string {
  return JSON.stringify(getTraceReport(), null, 2);
}

/**
 * Trigger a browser download of the trace buffer as a JSON file.
 *
 * Creates a Blob and uses a temporary <a> element to trigger the download.
 * Works in modern browsers. No-op on the server side.
 *
 * @param filename  Optional filename (default: "speech-trace.json").
 */
export function downloadTraceFile(filename: string = "speech-trace.json"): void {
  if (typeof document === "undefined" || typeof window === "undefined") {
    console.log("[SpeechTrace] downloadTraceFile: not in browser, skipping.");
    return;
  }
  const json = serializeTrace();
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
  console.log(`[SpeechTrace] Downloaded ${filename} (${blob.size} bytes)`);
}

// ── DevTools convenience export ───────────────────────────────────────────

if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).__SMARTDESK_SPEECH_TRACE__ = {
    getTraceReport,
    serializeTrace,
    downloadTraceFile,
    getTrace,
    clearTrace,
    isTraceEnabled,
  };
}
