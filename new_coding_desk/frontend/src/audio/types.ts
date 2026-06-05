/**
 * Speech audio stream states for the seat tablet UI.
 *
 * State machine:
 *   idle → requesting_microphone → connecting_speech_ws → recording
 *   recording → stopping → idle
 *   recording → idle  (via cancel)
 *   any error state → idle (via retry/reset)
 *
 * States mirror the protocol in docs/WEBSOCKET_PROTOCOL.md §3–4.
 */

export type SpeechStatus =
  | "idle"
  | "requesting_microphone"
  | "connecting_speech_ws"
  | "recording"
  | "stopping"
  | "error";

export interface SpeechState {
  status: SpeechStatus;
  error: string | null;
  utteranceId: string | null;
  sessionKey: string | null;
}
