// ─── UI ViewModel Types ─────────────────────────────────────────────────────
// These are derived from backend DTOs (api/types.ts) and are specific to the UI.
// Backend DTOs are imported directly from "@/api/types" where needed.

export type ConnectionStatus = "connecting" | "connected" | "disconnected";
export type AppMode = "admin" | "seat";

// ── Seat Display (synthesised by api/adapters.ts) ───────────────────────────
// Exactly 10 entries, one per physical seat.
// Speaker seat is an independent highlight, NOT a seat status.

export interface SeatDisplay {
  seatId: number;
  attendeeName: string | null;
  attendeeTitle: string | null;
  /** Stable attendee id from the backend (null when seat is vacant or no check-in). */
  attendeeId: number | null;
  isCheckedIn: boolean;
  isVacant: boolean;
  isSpeaker: boolean;
}

// ── Interim Translation (from WS translation_interim events) ──────────────────
// Displayed in TranscriptPanel as real-time subtitles, not persisted.
// Replaced by translation_final (persisted via GET /api/translations).

export interface InterimTranslation {
  utteranceId: string;
  seatId: number;
  revision: number;
  sourceLang: string;
  targetLang: string;
  sourceText: string;
  translatedText: string;
  requestedLanguage?: "auto" | "zh" | "en";
  detectedLanguage?: "unknown" | "zh" | "en";
  recognitionEngine?: "unknown" | "paraformer_streaming" | "sherpa_onnx_streaming" | "sensevoice_rolling_fallback";
  /** Exact two-line source window represented by translatedText. */
  translationSourceText?: string;
  /** Revision of the latest translated prefix; recognition may be newer. */
  translationRevision?: number;
  sentenceId?: string;
  sentenceSequence?: number;
  sentenceSourceText?: string;
  sentenceState?: "forming" | "completed";
  /** Optional two-line caption from backend caption formatter. */
  caption?: {
    previousLine: string;
    currentLine: string;
    mode: string;
  };
}

export interface LiveLyricSentence {
  utteranceId: string;
  sentenceId: string;
  sentenceSequence: number;
  seatId: number;
  revision: number;
  sourceLang: string;
  targetLang: string;
  sourceText: string;
  translatedText: string;
  translationStatus: "forming" | "pending" | "ok" | "unavailable";
  translationError?: string;
  recognitionStatus?: "correcting" | "ok" | "degraded";
  sourceLocked?: boolean;
}

export interface PendingTranslation {
  utteranceId: string;
  seatId: number;
  sourceLang: string;
  targetLang: string;
  sourceText: string;
  boundaryReason: string;
}
