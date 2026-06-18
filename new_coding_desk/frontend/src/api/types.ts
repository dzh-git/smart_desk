// ─── Backend DTO types matching docs/API_SPEC.md ──────────────────────────
// All fields use snake_case as returned by the backend API.
// These are distinct from the UI ViewModel types in ../types.ts.

// ── Status & Enum Types ───────────────────────────────────────────────────

export type MeetingStatus = "pending" | "active" | "finished";
export type SeatStatus = "vacant" | "occupied_unchecked" | "checked_in";
export type VoteStatus = "open" | "closed";
export type ServiceCallStatus = "pending" | "resolved" | "cancelled";
export type ServiceType = "coffee" | "tea" | "water" | "other";

// ── Standard API Response Envelope ───────────────────────────────────────

export interface ApiResponse<T> {
  success: boolean;
  message: string;
  data: T | null;
  error_code?: string | null;
}

// ── Meeting ───────────────────────────────────────────────────────────────

export interface Meeting {
  id: number;
  title: string;
  description: string | null;
  status: MeetingStatus;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

// ── Agenda ────────────────────────────────────────────────────────────────

export type AgendaStatus = "pending" | "active" | "completed" | "skipped";

export interface Agenda {
  id: number;
  meeting_id: number;
  title: string;
  sort_order: number;
  status: AgendaStatus;
  started_at: string | null;
  completed_at: string | null;
  skipped_at: string | null;
}

// ── Attendee ──────────────────────────────────────────────────────────────

export interface Attendee {
  id: number;
  meeting_id: number;
  name: string;
  title: string;
  seat_id: number | null;
  checked_in: boolean;
}

// ── Seat ──────────────────────────────────────────────────────────────────

export interface SeatState {
  seat_id: number;
  status: SeatStatus;
  attendee_id: number | null;
  updated_at: string;
}

export interface SpeakerSeat {
  seat_id: number | null;
}

// ── Vote ──────────────────────────────────────────────────────────────────

export interface Vote {
  id: number;
  meeting_id: number;
  title: string;
  options: string[];
  status: VoteStatus;
  is_anonymous: boolean;
}

export interface VoteOptionStat {
  option: string;
  count: number;
  attendee_ids: number[] | null;
}

export interface VoteStatistics {
  vote_id: number;
  title: string;
  is_anonymous: boolean;
  status: VoteStatus;
  total_votes: number;
  results: VoteOptionStat[];
}

// ── Service Call ──────────────────────────────────────────────────────────

export interface ServiceCall {
  id: number;
  meeting_id: number;
  seat_id: number;
  service_type: ServiceType;
  status: ServiceCallStatus;
  created_at: string | null;
}

// ── Translation ───────────────────────────────────────────────────────────

export interface TranslationRecord {
  id: number;
  meeting_id: number;
  seat_id: number;
  utterance_id?: string | null;
  source_lang: string;
  target_lang: string;
  source_text: string;
  translated_text: string;
  created_at: string;
  source_type?: string | null;
}

export interface TranslationHistoryResponse {
  meeting_id: number;
  entries: TranslationRecord[];
}

// ── Live Caption (from WS translation_interim.payload.caption) ────────────────

export interface CaptionPayload {
  previous_line: string;
  current_line: string;
  mode: string;
}

// ── Speech Model Status (Task 119) ─────────────────────────────────────────────

export type ModelComponentStatus = "unknown" | "loading" | "loaded" | "error";

export interface SpeechModelStatus {
  ready: boolean;
  preloading: boolean;
  streaming_model: ModelComponentStatus;
  offline_model: ModelComponentStatus;
  punctuation_model: ModelComponentStatus;
  punctuation_fallback: boolean;
  last_error: string | null;
}
