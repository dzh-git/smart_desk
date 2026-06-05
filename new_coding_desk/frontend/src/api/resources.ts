// ─── Resource-Specific API Methods ─────────────────────────────────────────
// Each function maps to one backend endpoint. Responses are already unwrapped
// by client.ts (ApiResponse envelope is stripped, only `data` is returned).
//
// See docs/API_SPEC.md for complete documentation.

import { apiGet, apiPost } from "./client";
import type {
  Meeting,
  SeatState,
  SpeakerSeat,
  Vote,
  VoteStatistics,
  ServiceCall,
  Agenda,
  Attendee,
  TranslationHistoryResponse,
  ServiceType,
} from "./types";

// ── Meeting ─────────────────────────────────────────────────────────────────

/** Returns the active meeting, or `null` when none exists. */
export function fetchActiveMeeting(): Promise<Meeting | null> {
  return apiGet<Meeting | null>("/meetings/active");
}

// ── Seats ───────────────────────────────────────────────────────────────────

/** Returns all 10 seat states. */
export function fetchSeats(): Promise<SeatState[]> {
  return apiGet<SeatState[]>("/seats");
}

/** Returns the current speaker seat (or null seat_id). */
export function fetchSpeakerSeat(): Promise<SpeakerSeat> {
  return apiGet<SpeakerSeat>("/seats/speaker");
}

// ── Votes ───────────────────────────────────────────────────────────────────

/** Returns the active (open) vote, or `null` when none exists. */
export function fetchActiveVote(): Promise<Vote | null> {
  return apiGet<Vote | null>("/votes/active");
}

/** Returns statistics for a specific vote (admin use). */
export function fetchVoteStatistics(
  voteId: number,
): Promise<VoteStatistics> {
  return apiGet<VoteStatistics>(`/votes/${voteId}/statistics`);
}

// ── Meeting Child Resources ─────────────────────────────────────────────────

/** Returns agenda items for a meeting, sorted by sort_order on the backend. */
export function fetchAgendas(meetingId: number): Promise<Agenda[]> {
  return apiGet<Agenda[]>(`/meetings/${meetingId}/agendas`);
}

/** Returns attendee list for a meeting. */
export function fetchAttendees(meetingId: number): Promise<Attendee[]> {
  return apiGet<Attendee[]>(`/meetings/${meetingId}/attendees`);
}

/** Returns service calls for a meeting. */
export function fetchServiceCalls(meetingId: number): Promise<ServiceCall[]> {
  return apiGet<ServiceCall[]>(
    `/service-calls?meeting_id=${meetingId}`,
  );
}

/** Returns translation history for a meeting. */
export function fetchTranslations(
  meetingId: number,
): Promise<TranslationHistoryResponse> {
  return apiGet<TranslationHistoryResponse>(
    `/translations?meeting_id=${meetingId}`,
  );
}

// ── Seat Check-in ────────────────────────────────────────────────────────────

/** Check in an attendee to a seat. */
export function checkinSeat(
  seatId: number,
  attendeeId: number,
): Promise<SeatState> {
  return apiPost<SeatState>(`/seats/${seatId}/checkin`, {
    attendee_id: attendeeId,
  });
}

// ── Dev Seat Controls (demo-only) ────────────────────────────────────────────

/** Dev-only: occupy a seat (vacant → occupied_unchecked). */
export function devOccupySeat(seatId: number): Promise<SeatState> {
  return apiPost<SeatState>(`/dev/seats/${seatId}/occupy`);
}

/** Dev-only: vacate a seat (any state → vacant). */
export function devVacateSeat(seatId: number): Promise<SeatState> {
  return apiPost<SeatState>(`/dev/seats/${seatId}/vacate`);
}

// ── Admin Vote Operations ──────────────────────────────────────────────────────

/** Create a new vote (admin). */
export function createVote(
  meetingId: number,
  title: string,
  options: string[],
  isAnonymous: boolean = false,
): Promise<Vote> {
  return apiPost<Vote>("/votes", {
    meeting_id: meetingId,
    title,
    options,
    is_anonymous: isAnonymous,
  });
}

/** Close an open vote (admin). */
export function closeVote(voteId: number): Promise<Vote> {
  return apiPost<Vote>(`/votes/${voteId}/close`);
}

// ── Vote Submission ──────────────────────────────────────────────────────────

/** Fetch a single vote by ID. */
export function fetchVote(voteId: number): Promise<Vote> {
  return apiGet<Vote>(`/votes/${voteId}`);
}

/** Submit or update a ballot. */
export function submitVote(
  voteId: number,
  attendeeId: number,
  option: string,
): Promise<Vote> {
  return apiPost<Vote>(`/votes/${voteId}/submit`, {
    attendee_id: attendeeId,
    option,
  });
}

// ── Service Calls (Seat Actions) ─────────────────────────────────────────────

/** Get the current (pending) service call for a seat. */
export function fetchCurrentServiceCall(
  meetingId: number,
  seatId: number,
): Promise<ServiceCall | null> {
  return apiGet<ServiceCall | null>(
    `/service-calls/current?meeting_id=${meetingId}&seat_id=${seatId}`,
  );
}

/** Create a new service call. */
export function createServiceCall(
  meetingId: number,
  seatId: number,
  serviceType: ServiceType,
): Promise<ServiceCall> {
  return apiPost<ServiceCall>(
    `/service-calls?meeting_id=${meetingId}`,
    { seat_id: seatId, service_type: serviceType },
  );
}

/** Cancel a pending service call. */
export function cancelServiceCall(callId: number): Promise<ServiceCall> {
  return apiPost<ServiceCall>(`/service-calls/${callId}/cancel`);
}

/** Resolve a pending service call (admin). */
export function resolveServiceCall(callId: number): Promise<ServiceCall> {
  return apiPost<ServiceCall>(`/service-calls/${callId}/resolve`);
}
