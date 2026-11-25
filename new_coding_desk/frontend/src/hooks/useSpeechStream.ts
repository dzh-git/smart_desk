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
import type { SpeechLanguageMode } from "../audio/speechWsClient";
import type { SpeechStatus } from "../audio/types";
import { subscribeNativeEvents } from "../native/nativeEvents";

import { trace } from "../audio/speechTrace";

// ---- Options ----

/**
 * Optional configuration for useSpeechStream.
 * Task 127A: local cleanup callback to immediately remove live caption
 * when Cancel is clicked or Stop timeout fires, without waiting for the
 * backend WebSocket roundtrip.
 */
export interface UseSpeechStreamOptions {
  /**
   * Called with (utteranceId, reason) when the local UI should immediately
   * terminate the utterance's live caption.
   * reason is "cancel" or "stop_timeout".
   * The callback should remove the utterance from interimMap and mark it
   * terminal so late interims are ignored.
   */
  onLocalTerminalUtterance?: (utteranceId: string, reason: string) => void;
}

// ---- Public interface ----

export interface UseSpeechStreamReturn {
  /** Current speech status for UI rendering. */
  status: SpeechStatus;
  /** Human-readable error message (only when status === "error"). */
  error: string | null;
  /** Current utterance ID from the backend, or null if not started. */
  utteranceId: string | null;
  /** Requested recognition language, persisted independently per seat. */
  languageMode: SpeechLanguageMode;
  /** Change language while idle; recording keeps the utterance route locked. */
  setLanguageMode: (mode: SpeechLanguageMode) => void;
  /** Start recording: request mic → connect WS → stream audio. */
  start: () => Promise<void>;
  /** Release the microphone and send end_hint for server finalization. */
  stop: () => void;
  /** Cancel mid-utterance: send cancel → close WS → stop mic. */
  cancel: () => void;
}

// ---- Hook ----

export function useSpeechStream(
  meetingId: number | null,
  seatId: number,
  canCapture: boolean,
  options?: UseSpeechStreamOptions,
): UseSpeechStreamReturn {
  const [status, setStatus] = useState<SpeechStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [utteranceId, setUtteranceId] = useState<string | null>(null);
  const storageKey = `smartdesk.speechLanguageMode.${seatId}`;
  const [languageMode, setLanguageModeState] = useState<SpeechLanguageMode>(() => {
    if (typeof window === "undefined") return "auto";
    const stored = window.localStorage.getItem(storageKey);
    return stored === "zh" || stored === "en" ? stored : "auto";
  });

  // Mutable refs for lifecycle management
  const micRef = useRef<MicrophoneCapture | null>(null);
  const wsRef = useRef<SpeechWsClient | null>(null);
  const startingRef = useRef(false);
  const recordingRef = useRef(false);
  const reconnectingRef = useRef(false);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const generationRef = useRef(0);
  const mountedRef = useRef(true);
  const utteranceIdRef = useRef<string | null>(null);
  const languageModeRef = useRef<SpeechLanguageMode>(languageMode);
  languageModeRef.current = languageMode;
  // Task 126: stop delay timer ref — cleared on immediate cleanup/cancel/unmount
  const stopTimerRef = useRef<number | null>(null);
  // Task 127A: stable ref for options (avoids useCallback dependency churn)
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const setLanguageMode = useCallback((mode: SpeechLanguageMode) => {
    if (recordingRef.current || startingRef.current) return;
    languageModeRef.current = mode;
    setLanguageModeState(mode);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(storageKey, mode);
    }
    trace("speech_language_mode_changed_at", { seatId, languageMode: mode });
  }, [seatId, storageKey]);

  // ---- Cleanup (internal) ----

  const releaseMicrophone = useCallback(() => {
    const mic = micRef.current;
    micRef.current = null;
    mic?.stop();
  }, []);

  const cleanup = useCallback(() => {
    startingRef.current = false;
    recordingRef.current = false;
    reconnectingRef.current = false;
    reconnectAttemptsRef.current = 0;
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    // Task 126: clear any pending stop delay timer
    if (stopTimerRef.current !== null) {
      clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
    trace("speech_cleanup_at", { utteranceId: utteranceIdRef.current ?? undefined });
    const ws = wsRef.current;
    wsRef.current = null;
    ws?.close();
    releaseMicrophone();
    utteranceIdRef.current = null;
  }, [releaseMicrophone]);

  // ---- Start ----

  const start = useCallback(async () => {
    if (
      !meetingId || !canCapture || recordingRef.current || startingRef.current
    ) return;

    const generation = generationRef.current + 1;
    generationRef.current = generation;
    startingRef.current = true;
    reconnectAttemptsRef.current = 0;
    const isCurrent = () => (
      mountedRef.current && generationRef.current === generation
    );

    trace("start_clicked_at", {
      meetingId,
      seatId,
      languageMode: languageModeRef.current,
    });
    setStatus("requesting_microphone");
    setError(null);

    const mic = new MicrophoneCapture();
    let wsClient: SpeechWsClient | null = null;
    micRef.current = mic;

    const forwardAudio = (pcm16: ArrayBufferLike) => {
      if (isCurrent() && recordingRef.current) {
        trace("frontend_pcm_sent_at", { size: pcm16.byteLength });
        wsRef.current?.sendAudio(pcm16);
      }
    };

    const failMicrophone = (micError: string) => {
      if (!isCurrent()) return;
      generationRef.current += 1;
      cleanup();
      setError(micError);
      setStatus("error");
    };

    const disposeAttempt = () => {
      if (wsRef.current === wsClient) wsRef.current = null;
      wsClient?.close();
      if (micRef.current === mic) micRef.current = null;
      mic.stop();
    };

    trace("microphone_start_requested_at", { meetingId, seatId });

    try {
      await mic.start(
        forwardAudio,
        failMicrophone,
      );
    } catch (err) {
      if (!isCurrent()) {
        disposeAttempt();
        return;
      }
      generationRef.current += 1;
      startingRef.current = false;
      disposeAttempt();
      const msg =
        err instanceof Error ? err.message : "Microphone access denied";
      setError(msg);
      setStatus("error");
      return;
    }

    if (!isCurrent()) {
      disposeAttempt();
      return;
    }

    const scheduleReconnect = () => {
      if (
        !isCurrent() || !recordingRef.current || reconnectingRef.current
        || reconnectTimerRef.current !== null
      ) return;

      if (reconnectAttemptsRef.current >= 3) {
        generationRef.current += 1;
        cleanup();
        setError("Speech connection lost; microphone released");
        setStatus("error");
        return;
      }

      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        if (!isCurrent() || !recordingRef.current) return;

        reconnectAttemptsRef.current += 1;
        reconnectingRef.current = true;
        setStatus("connecting_speech_ws");
        trace("speech_ws_reconnect_start_at", { meetingId, seatId });

        const replacement = createWsClient();
        replacement.connect(
          meetingId,
          seatId,
          languageModeRef.current,
        ).then(async (result) => {
          if (
            !isCurrent() || !recordingRef.current
            || wsRef.current !== replacement
          ) {
            replacement.close();
            return;
          }
          const replacementMicrophone = new MicrophoneCapture();
          micRef.current = replacementMicrophone;
          try {
            await replacementMicrophone.start(
              forwardAudio,
              failMicrophone,
            );
          } catch (err) {
            if (!isCurrent()) {
              replacementMicrophone.stop();
              return;
            }
            replacement.sendCancel();
            generationRef.current += 1;
            cleanup();
            setError(
              err instanceof Error
                ? err.message
                : "Microphone access denied",
            );
            setStatus("error");
            return;
          }
          if (
            !isCurrent() || !recordingRef.current
            || wsRef.current !== replacement
          ) {
            replacementMicrophone.stop();
            return;
          }
          utteranceIdRef.current = result.utteranceId;
          setUtteranceId(result.utteranceId);
          reconnectingRef.current = false;
          reconnectAttemptsRef.current = 0;
          setError(null);
          setStatus("recording");
          trace("speech_ws_reconnected_at", {
            meetingId,
            seatId,
            utteranceId: result.utteranceId,
          });
        }).catch(() => {
          if (!isCurrent() || !recordingRef.current) return;
          reconnectingRef.current = false;
          scheduleReconnect();
        });
      }, 500);
    };

    const createWsClient = () => {
      const client = new SpeechWsClient();
      wsClient = client;
      wsRef.current = client;
      client.onUtteranceStarted((newUtteranceId: string) => {
        if (!isCurrent() || !recordingRef.current) return;
        utteranceIdRef.current = newUtteranceId;
        setUtteranceId(newUtteranceId);
      });
      client.onStatusChange((nextStatus) => {
        if (
          nextStatus !== "disconnected" || !isCurrent()
          || !recordingRef.current || wsRef.current !== client
        ) return;
        wsRef.current = null;
        releaseMicrophone();
        reconnectingRef.current = false;
        scheduleReconnect();
      });
      return client;
    };

    setStatus("connecting_speech_ws");
    wsClient = createWsClient();

    try {
      const result = await wsClient.connect(
        meetingId,
        seatId,
        languageModeRef.current,
      );
      if (!isCurrent()) {
        disposeAttempt();
        return;
      }
      utteranceIdRef.current = result.utteranceId;
      setUtteranceId(result.utteranceId);
      startingRef.current = false;
      recordingRef.current = true;
      setStatus("recording");
    } catch (err) {
      if (!isCurrent()) {
        disposeAttempt();
        return;
      }
      generationRef.current += 1;
      startingRef.current = false;
      recordingRef.current = false;
      disposeAttempt();
      const msg =
        err instanceof Error ? err.message : "Failed to connect speech service";
      setError(msg);
      setStatus("error");
    }
  }, [canCapture, cleanup, meetingId, releaseMicrophone, seatId]);

  // ---- Stop (end_hint path) ----

  const stop = useCallback(() => {
    if (!recordingRef.current) return;
    const generation = generationRef.current;
    const uid = utteranceIdRef.current;
    recordingRef.current = false;
    releaseMicrophone();
    trace("stop_clicked_at", { utteranceId: uid ?? undefined });
    setStatus("stopping");

    // Send end_hint — backend needs time to finalize and broadcast
    wsRef.current?.sendEndHint();

    // Task 126: delay WS close to give backend a finalization window.
    // After 2000ms, cleanup and return to idle if still mounted.
    // Component unmount or cancel will clear this timer and cleanup immediately.
    if (stopTimerRef.current !== null) clearTimeout(stopTimerRef.current);
    stopTimerRef.current = window.setTimeout(() => {
      stopTimerRef.current = null;
      if (mountedRef.current && generationRef.current === generation) {
        // Task 127A: local cleanup on stop timeout — immediately remove
        // live caption so it doesn't linger if translation_final never arrives
        if (uid && optionsRef.current?.onLocalTerminalUtterance) {
          optionsRef.current.onLocalTerminalUtterance(uid, "stop_timeout");
        }
        generationRef.current += 1;
        cleanup();
        setStatus("idle");
        setUtteranceId(null);
      }
    }, 2000);
  }, [cleanup, releaseMicrophone]);

  // ---- Cancel ----

  const cancel = useCallback(() => {
    const uid = utteranceIdRef.current;
    generationRef.current += 1;
    startingRef.current = false;
    recordingRef.current = false;
    trace("cancel_clicked_at", { utteranceId: uid ?? undefined });

    // Task 127A: local cleanup before WS message — immediately remove
    // live caption so the UI doesn't wait for translation_interim_cancelled
    if (uid && optionsRef.current?.onLocalTerminalUtterance) {
      optionsRef.current.onLocalTerminalUtterance(uid, "cancel");
    }

    // Send cancel before closing
    wsRef.current?.sendCancel();
    cleanup();

    setStatus("idle");
    setError(null);
    utteranceIdRef.current = null;
    setUtteranceId(null);
  }, [cleanup]);

  // ---- Auto-cleanup on unmount or when capture permission is lost ----

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      cleanup();
    };
  }, [cleanup]);

  useEffect(() => {
    if (
      (!canCapture || !meetingId)
      && (startingRef.current || recordingRef.current || stopTimerRef.current !== null)
    ) {
      cancel();
    }
  }, [canCapture, cancel, meetingId]);

  // Android Activity pause, browser backgrounding, and page teardown must
  // release both getUserMedia and the speech WebSocket immediately.
  useEffect(() => {
    const releaseForPageLifecycle = () => {
      if (
        startingRef.current ||
        recordingRef.current ||
        stopTimerRef.current !== null ||
        micRef.current !== null ||
        wsRef.current !== null
      ) {
        cancel();
      }
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        releaseForPageLifecycle();
      }
    };
    const unsubscribeNative = subscribeNativeEvents((event) => {
      if (
        event.type === "app_lifecycle" &&
        typeof event.data === "object" &&
        event.data !== null &&
        "state" in event.data &&
        event.data.state !== "RESUMED"
      ) {
        releaseForPageLifecycle();
      }
    });
    window.addEventListener("pagehide", releaseForPageLifecycle);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      unsubscribeNative();
      window.removeEventListener("pagehide", releaseForPageLifecycle);
      document.removeEventListener(
        "visibilitychange",
        onVisibilityChange,
      );
    };
  }, [cancel]);

  return {
    status,
    error,
    utteranceId,
    languageMode,
    setLanguageMode,
    start,
    stop,
    cancel,
  };
}
