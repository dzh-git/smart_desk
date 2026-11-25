// ─── WebSocket Hook ────────────────────────────────────────────────────────
// Manages connection lifecycle, auto-reconnect, and event dispatch.
// Only receives server messages — never sends business data over WS.
//
// See docs/WEBSOCKET_PROTOCOL.md for the complete protocol spec.

import { useEffect, useRef, useCallback, useState } from "react";
import type { ConnectionStatus } from "../types";
import { wsBase } from "../app-config";

// ── Types ──────────────────────────────────────────────────────────────────

export interface WSMessage {
  event: string;
  meeting_id: number;
  timestamp: number;
  payload: Record<string, unknown>;
}

type EventHandler = (event: string, message: WSMessage) => void;

const RECONNECT_INTERVAL_MS = 3000;

// ── Hook ───────────────────────────────────────────────────────────────────

/**
 * Opens a WebSocket connection for the given meeting.
 *
 * - Auto-reconnects every 3 s after disconnect.
 * - Calls `onEvent` for every received message.
 * - Returns the current connection status.
 *
 * Pass `meetingId={null}` to keep the connection closed.
 * Pass `seatId` to connect as a specific seat (e.g. /ws/{id}?seat={n}).
 * When omitted or 0, connects as admin (/ws/{id}?seat=0).
 */
export function useWebSocket(
  meetingId: number | null,
  onEvent: EventHandler,
  seatId?: number,
): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");

  // Keep the latest onEvent in a ref so we never need to re-create the WS
  // when the callback changes.
  const onEventRef = useRef<EventHandler>(onEvent);
  onEventRef.current = onEvent;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  /** Tracks whether the very first connection attempt has completed.
   *  Subsequent connections are reconnections and trigger a full refresh. */
  const firstConnectDoneRef = useRef(false);

  const connect = useCallback(() => {
    // Clean up any previous reconnect timer
    if (reconnectRef.current !== null) {
      clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }

    if (!mountedRef.current) return;
    if (!meetingId) {
      setStatus("disconnected");
      return;
    }

    setStatus("connecting");

    const wsSeatId = seatId ?? 0;
    const url = `${wsBase()}/ws/${meetingId}?seat=${wsSeatId}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current || wsRef.current !== ws) return;
      setStatus("connected");
      if (firstConnectDoneRef.current) {
        // Reconnection — trigger full HTTP re-fetch per WEBSOCKET_PROTOCOL §4
        onEventRef.current("reconnected", {
          event: "reconnected",
          meeting_id: meetingId,
          timestamp: Math.floor(Date.now() / 1000),
          payload: {},
        });
      }
      firstConnectDoneRef.current = true;
    };

    ws.onmessage = (event: MessageEvent) => {
      if (wsRef.current !== ws) return;
      try {
        const msg: WSMessage = JSON.parse(event.data as string);
        onEventRef.current(msg.event, msg);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current || wsRef.current !== ws) return;
      wsRef.current = null;
      setStatus("disconnected");
      // Schedule reconnect
      reconnectRef.current = setTimeout(connect, RECONNECT_INTERVAL_MS);
    };

    ws.onerror = () => {
      // onclose will fire after onerror, so close triggers reconnect
      ws.close();
    };
  }, [meetingId, seatId]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;

      if (reconnectRef.current !== null) {
        clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }

      if (wsRef.current) {
        // Prevent reconnect on intentional close
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return status;
}
