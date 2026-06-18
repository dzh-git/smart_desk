"""
SpeechTrace — temporary diagnostic instrumentation for Task 125 audit.

This is a TEMPORARY diagnostic module. It is NOT a product feature.
It records timestamped events keyed by utterance_id for latency analysis.
No data is persisted to database, no API exposes it.

## DEFAULT OFF
Tracing is DISABLED by default. Enable with the environment variable:
    SMART_DESK_ENABLE_SPEECH_TRACE=true
When disabled, trace() is a no-op and the ring buffer stays empty.

## Ring buffer
The buffer holds at most MAX_ENTRIES events. When full, the oldest event
is discarded. This prevents unbounded memory growth during long meetings.

Usage:
    from backend.websocket.speech_trace import trace, get_trace, clear_trace
    trace("backend_pcm_received_at", utterance_id="utt_1_1_000001",
          meeting_id=1, seat_id=1)
"""
from __future__ import annotations

import os
import time
import threading
from typing import Any

# ── Configuration ──────────────────────────────────────────────────────────────

MAX_ENTRIES: int = 1000

# Check at import time; set SMART_DESK_ENABLE_SPEECH_TRACE=true to enable.
_enabled: bool = (
    os.environ.get("SMART_DESK_ENABLE_SPEECH_TRACE", "").lower() == "true"
)

# ── Internal state ─────────────────────────────────────────────────────────────

_trace_lock: threading.Lock = threading.Lock()
_trace_buffer: list[dict[str, Any]] = []


def trace(
    event: str,
    utterance_id: str | None = None,
    meeting_id: int | None = None,
    seat_id: int | None = None,
    **extra: Any,
) -> None:
    """Record a trace event with timestamp (monotonic ms) and metadata.

    No-op unless SMART_DESK_ENABLE_SPEECH_TRACE=true.

    Args:
        event: Event name, e.g. "backend_pcm_received_at".
        utterance_id: Correlating utterance_id (may be None for
                      session-level events).
        meeting_id: Active meeting ID.
        seat_id: Speaker seat ID.
        extra: Additional key-value pairs (e.g. revision, duration_ms).
    """
    if not _enabled:
        return

    record: dict[str, Any] = {
        "event": event,
        "timestamp_monotonic_ms": time.monotonic_ns() // 1_000_000,
        "timestamp_wall_ms": int(time.time() * 1000),
    }
    if utterance_id is not None:
        record["utterance_id"] = utterance_id
    if meeting_id is not None:
        record["meeting_id"] = meeting_id
    if seat_id is not None:
        record["seat_id"] = seat_id
    record.update(extra)

    with _trace_lock:
        _trace_buffer.append(record)
        # Ring buffer: discard oldest when over capacity
        if len(_trace_buffer) > MAX_ENTRIES:
            _trace_buffer.pop(0)


def get_trace() -> list[dict[str, Any]]:
    """Return a copy of all recorded trace events."""
    with _trace_lock:
        return list(_trace_buffer)


def clear_trace() -> None:
    """Clear all recorded trace events. Safe to call multiple times."""
    with _trace_lock:
        _trace_buffer.clear()


def is_trace_enabled() -> bool:
    """True when SMART_DESK_ENABLE_SPEECH_TRACE=true."""
    return _enabled


# ── File export (for Task 128E merged latency report) ────────────────────────


def export_trace_to_file(path: str) -> dict[str, object]:
    """Export the current trace buffer to a JSON file.

    The exported file contains all events plus metadata and can be consumed
    by ``generate_latency_report.py --backend-trace <path>``.

    Args:
        path: File path to write the JSON export to.

    Returns:
        dict with keys: success (bool), event_count (int),
        path (str), error (str|None).
    """
    events = get_trace()
    export: dict[str, object] = {
        "exported_at": int(time.time() * 1000),
        "trace_enabled": _enabled,
        "event_count": len(events),
        "events": events,
    }
    try:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2, default=str)
        return {
            "success": True,
            "event_count": len(events),
            "path": path,
            "error": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "event_count": len(events),
            "path": path,
            "error": str(exc),
        }


def load_trace_from_file(path: str) -> dict[str, object]:
    """Load a previously exported trace file.

    Compatible with files written by export_trace_to_file().

    Args:
        path: Path to a backend trace JSON file.

    Returns:
        dict with keys: available (bool), events (list),
        event_count (int), note (str|None).
    """
    result: dict[str, object] = {
        "available": False,
        "events": [],
        "event_count": 0,
        "note": None,
    }
    path_obj = Path(path) if "Path" in dir() else __import__("pathlib").Path(path)
    if not path_obj.exists():
        result["note"] = f"Backend trace file not found: {path}"
        return result
    try:
        import json
        with open(path_obj, "r", encoding="utf-8") as f:
            raw = json.load(f)
        raw_events = raw.get("events", [])
        result["available"] = True
        result["events"] = raw_events
        result["event_count"] = len(raw_events)
        result["note"] = f"Backend trace loaded from file: {len(raw_events)} events"
    except (json.JSONDecodeError, OSError) as exc:
        result["note"] = f"Failed to load backend trace file: {exc}"
    return result
