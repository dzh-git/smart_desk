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
  /** Optional two-line caption from backend caption formatter. */
  caption?: {
    previousLine: string;
    currentLine: string;
    mode: string;
  };
}
