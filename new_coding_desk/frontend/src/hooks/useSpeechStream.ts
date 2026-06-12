/**
 * useSpeechStream — Orchestrates microphone capture and /ws/speech uplink.
 *
 * State machine (docs/WEBSOCKET_PROTOCOL.md §3–4):
 *
 *   idle → requesting_microphone → connecting_speech_ws → recording
 *   recording → stopping → idle                    (end_hint path)
 *   recording → idle                                (cancel path)
 *   any → error → idle                              (retry)
 *
 * The hook owns the full lifecycle: mic request, WS connection, frame
 * forwarding, end_hint/cancel signalling, and cleanup on unmount.
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { MicrophoneCapture } from "../audio/microphone";
import { SpeechWsClient } from "../audio/speechWsClient";
import type { SpeechStatus } from "../audio/types";

// ---- Public interface ----

export interface UseSpeechStreamReturn {
  /** Current speech status for UI rendering. */
  status: SpeechStatus;
  /** Human-readable error message (only when status === "error"). */
  error: string | null;
  /** Current utterance ID from the backend, or null if not started. */
  utteranceId: string | null;
  /** Start recording: request mic → connect WS → stream audio. */
  start: () => Promise<void>;
  /** Stop recording: send end_hint → close WS → stop mic. */
  stop: () => void;
  /** Cancel mid-utterance: send cancel → close WS → stop mic. */
  cancel: () => void;
}

// ---- Hook ----

export function useSpeechStream(
  meetingId: number | null,
  seatId: number,
  isSpeaker: boolean,
): UseSpeechStreamReturn {
  const [status, setStatus] = useState<SpeechStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [utteranceId, setUtteranceId] = useState<string | null>(null);

  // Mutable refs for lifecycle management
  const micRef = useRef<MicrophoneCapture | null>(null);
  const wsRef = useRef<SpeechWsClient | null>(null);
  const recordingRef = useRef(false);
  const mountedRef = useRef(true);

  // ---- Cleanup (internal) ----

  const cleanup = useCallback(() => {
    recordingRef.current = false;
    wsRef.current?.close();
    wsRef.current = null;
    micRef.current?.stop();
    micRef.current = null;
  }, []);

  // ---- Start ----

  const start = useCallback(async () => {
    if (!meetingId || !isSpeaker || recordingRef.current) return;

    setStatus("requesting_microphone");
    setError(null);

    // 1. Create and start microphone capture
    const mic = new MicrophoneCapture();
    micRef.current = mic;

    try {
      await mic.start(
        // onFrame: forward PCM16 to speech WS
        (pcm16) => {
          if (recordingRef.current && wsRef.current) {
            wsRef.current.sendAudio(pcm16);
          }
        },
        // onError: surface microphone errors
        (micError) => {
          if (mountedRef.current) {
            setError(micError);
            setStatus("error");
            recordingRef.current = false;
          }
        },
      );
    } catch (err) {
      if (!mountedRef.current) return;
      const msg =
        err instanceof Error ? err.message : "Microphone access denied";
      setError(msg);
      setStatus("error");
      return;
    }

    if (!mountedRef.current) {
      mic.stop();
      return;
    }

    // 2. Connect speech WebSocket
    setStatus("connecting_speech_ws");

    const wsClient = new SpeechWsClient();
    wsRef.current = wsClient;

    // Task 122: listen for utterance_started from backend auto-final.
    // When the backend automatically finalizes and starts a new utterance,
    // update our tracked utteranceId so the UI stays in sync.
    wsClient.onUtteranceStarted((newUtteranceId: string) => {
      if (mountedRef.current) {
        setUtteranceId(newUtteranceId);
      }
    });

    try {
      const result = await wsClient.connect(meetingId, seatId);
      if (!mountedRef.current) {
        wsClient.close();
        mic.stop();
        return;
      }
      setUtteranceId(result.utteranceId);
      recordingRef.current = true;
      setStatus("recording");
    } catch (err) {
      if (!mountedRef.current) return;
      const msg =
        err instanceof Error ? err.message : "Failed to connect speech service";
      setError(msg);
      setStatus("error");
      mic.stop();
      micRef.current = null;
    }
  }, [meetingId, seatId, isSpeaker]);

  // ---- Stop (end_hint path) ----

  const stop = useCallback(() => {
    if (!recordingRef.current) return;
    recordingRef.current = false;
    setStatus("stopping");

    // Send end_hint before closing
    wsRef.current?.sendEndHint();
    cleanup();

    setStatus("idle");
    setUtteranceId(null);
  }, [cleanup]);

  // ---- Cancel ----

  const cancel = useCallback(() => {
    recordingRef.current = false;

    // Send cancel before closing
    wsRef.current?.sendCancel();
    cleanup();

    setStatus("idle");
    setError(null);
    setUtteranceId(null);
  }, [cleanup]);

  // ---- Auto-cleanup on unmount or when isSpeaker becomes false ----

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [cleanup]);

  // Stop recording if speaker seat is revoked mid-stream
  useEffect(() => {
    if (!isSpeaker && recordingRef.current) {
      cancel();
    }
  }, [isSpeaker, cancel]);

  return { status, error, utteranceId, start, stop, cancel };
}
