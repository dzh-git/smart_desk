// ─── Resource-Specific API Methods ─────────────────────────────────────────
// Each function maps to one backend endpoint. Responses are already unwrapped
// by client.ts (ApiResponse envelope is stripped, only `data` is returned).
//
// See docs/API_SPEC.md for complete documentation.

import {
  apiDelete,
  apiGet,
  apiGetRaw,
  apiPost,
  apiPut,
  apiRequest,
} from "./client";
import type {
  Meeting,
  SeatState,
  SpeakerSeat,
  Vote,
  VoteStatistics,
  ServiceCall,
  Agenda,
  Attendee,
  Person,
  IdentityCheckInPayload,
  TabletVacatePayload,
  DebugAdmitPayload,
  TabletDeviceStatus,
  TabletHeartbeatPayload,
  TranslationHistoryResponse,
  ServiceType,
} from "./types";

// ── Meeting ─────────────────────────────────────────────────────────────────

/** Returns the active meeting, or `null` when none exists. */
export function fetchActiveMeeting(): Promise<Meeting | null> {
  return apiGet<Meeting | null>("/meetings/active");
}

/** Returns all meetings, newest first as provided by the backend. */
export function fetchMeetings(): Promise<Meeting[]> {
  return apiGet<Meeting[]>("/meetings");
}

/** Create a pending meeting. */
export function createMeeting(
  title: string,
  description?: string,
): Promise<Meeting> {
  return apiPost<Meeting>("/meetings", {
    title,
    description: description?.trim() || null,
  });
}

/** Start a pending meeting. */
export function startMeeting(meetingId: number): Promise<Meeting> {
  return apiPost<Meeting>(`/meetings/${meetingId}/start`);
}

/** End an active meeting. */
export function endMeeting(meetingId: number): Promise<Meeting> {
  return apiPost<Meeting>(`/meetings/${meetingId}/end`);
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

/** Set the current speaker seat. */
export function setSpeakerSeat(seatId: number): Promise<SpeakerSeat> {
  return apiPost<SpeakerSeat>("/seats/speaker", { seat_id: seatId });
}

/** Clear the current speaker seat. */
export function clearSpeakerSeat(): Promise<SpeakerSeat> {
  return apiDelete<SpeakerSeat>("/seats/speaker");
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

/** Returns all votes for a meeting, newest first. */
export async function fetchVotesForMeeting(
  meetingId: number,
): Promise<Vote[]> {
  return (await apiGet<Vote[] | null>(`/votes?meeting_id=${meetingId}`)) ?? [];
}

/** Returns statistics for all votes in a meeting, newest first. */
export async function fetchVoteResultsForMeeting(
  meetingId: number,
): Promise<VoteStatistics[]> {
  const votes = await fetchVotesForMeeting(meetingId);
  return Promise.all(votes.map((vote) => fetchVoteStatistics(vote.id)));
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

/** Add an attendee to a meeting. */
export function createAttendee(
  meetingId: number,
  name: string,
  title: string = "",
  personId?: string,
): Promise<Attendee> {
  return apiPost<Attendee>(`/meetings/${meetingId}/attendees`, {
    name,
    title,
    ...(personId ? { personId } : {}),
  });
}

/** List stable people available for meeting attendee assignment. */
export function fetchPeople(): Promise<Person[]> {
  return apiGet<Person[]>("/people");
}

/** Create a stable person identity before face enrollment. */
export function createPerson(id: string, name: string): Promise<Person> {
  return apiPost<Person>("/people", { id, name });
}

/** Delete an attendee from a meeting. */
export function deleteAttendee(
  meetingId: number,
  attendeeId: number,
): Promise<void> {
  return apiDelete<void>(`/meetings/${meetingId}/attendees/${attendeeId}`);
}

/** Assign the meeting's default attendee to a physical seat. */
export function setSeatAssignment(
  meetingId: number,
  seatId: number,
  attendeeId: number,
): Promise<Attendee> {
  return apiPut<Attendee>(
    `/meetings/${meetingId}/seat-assignments/${seatId}`,
    { attendeeId },
  );
}

/** Clear a seat's default attendee assignment. */
export function clearSeatAssignment(
  meetingId: number,
  seatId: number,
): Promise<void> {
  return apiDelete<void>(
    `/meetings/${meetingId}/seat-assignments/${seatId}`,
  );
}

/** Host fallback admission for the attendee assigned to the seat. */
export function manualAdmitSeat(seatId: number): Promise<SeatState> {
  return apiPost<SeatState>(`/seats/${seatId}/manual-admit`);
}

/** Add an agenda item to a meeting. */
export function createAgenda(
  meetingId: number,
  title: string,
  sortOrder: number,
): Promise<Agenda> {
  return apiPost<Agenda>(`/meetings/${meetingId}/agendas`, {
    title,
    sort_order: sortOrder,
  });
}

/** Delete an agenda item from a meeting. */
export function deleteAgenda(
  meetingId: number,
  agendaId: number,
): Promise<void> {
  return apiDelete<void>(`/meetings/${meetingId}/agendas/${agendaId}`);
}

/** Set a pending/skipped agenda as the current active topic. */
export function setCurrentAgenda(
  meetingId: number,
  agendaId: number,
): Promise<void> {
  return apiPost<void>(
    `/meetings/${meetingId}/agendas/${agendaId}/set-current`,
  );
}

/** Complete the current active topic and activate the next pending topic. */
export function advanceAgenda(meetingId: number): Promise<void> {
  return apiPost<void>(`/meetings/${meetingId}/agendas/advance`);
}

/** Complete the current active agenda. */
export function completeAgenda(
  meetingId: number,
  agendaId: number,
): Promise<void> {
  return apiPost<void>(
    `/meetings/${meetingId}/agendas/${agendaId}/complete`,
  );
}

/** Skip the current active agenda. */
export function skipAgenda(
  meetingId: number,
  agendaId: number,
): Promise<void> {
  return apiPost<void>(
    `/meetings/${meetingId}/agendas/${agendaId}/skip`,
  );
}

/** Returns service calls for a meeting. */
export function fetchServiceCalls(meetingId: number): Promise<ServiceCall[]> {
  return apiGet<ServiceCall[]>(
    `/service-calls?meeting_id=${meetingId}`,
  );
}

/** Returns translation history for a meeting, optionally filtered by seat. */
export function fetchTranslations(
  meetingId: number,
  seatId?: number,
): Promise<TranslationHistoryResponse> {
  let path = `/translations?meeting_id=${meetingId}`;
  if (seatId !== undefined) {
    path += `&seat_id=${seatId}`;
  }
  return apiGet<TranslationHistoryResponse>(path);
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

/**
 * Submit Android's local identity evidence for server-side policy checks.
 * The server maps personId to the active meeting attendee and reuses the
 * existing SeatService check-in state machine.
 */
export function identityCheckinSeat(
  seatId: number,
  payload: IdentityCheckInPayload,
  deviceToken: string,
): Promise<SeatState> {
  return apiRequest<SeatState>(`/seats/${seatId}/identity-checkin`, {
    method: "POST",
    headers: {
      "X-SmartDesk-Device-Token": deviceToken,
    },
    body: JSON.stringify(payload),
  });
}

export function tabletVacateSeat(
  seatId: number,
  payload: TabletVacatePayload,
  deviceToken: string,
): Promise<SeatState> {
  return apiRequest<SeatState>(`/seats/${seatId}/tablet-vacate`, {
    method: "POST",
    headers: {
      "X-SmartDesk-Device-Token": deviceToken,
    },
    body: JSON.stringify(payload),
  });
}

export function debugAdmitSeat(
  seatId: number,
  payload: DebugAdmitPayload,
  deviceToken: string,
): Promise<SeatState> {
  return apiRequest<SeatState>(`/seats/${seatId}/debug-admit`, {
    method: "POST",
    headers: {
      "X-SmartDesk-Device-Token": deviceToken,
    },
    body: JSON.stringify(payload),
  });
}

export function reportTabletHeartbeat(
  deviceId: string,
  payload: TabletHeartbeatPayload,
  deviceToken: string,
): Promise<TabletDeviceStatus> {
  return apiRequest<TabletDeviceStatus>(
    `/tablet-devices/${encodeURIComponent(deviceId)}/heartbeat`,
    {
      method: "POST",
      headers: {
        "X-SmartDesk-Device-Token": deviceToken,
      },
      body: JSON.stringify(payload),
    },
  );
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

// ── Speech Model Status (Task 119) ─────────────────────────────────────────────

/** Returns unified speech model readiness state. */
export function fetchSpeechStatus(): Promise<import("./types").SpeechModelStatus> {
  return apiGet<import("./types").SpeechModelStatus>("/speech/status");
}

/** Trigger background model preload (non-blocking). */
export function triggerSpeechPreload(): Promise<void> {
  return apiPost<void>("/speech/preload");
}

// ── Host Display Status (Screen Stream) ────────────────────────────────────

/**
 * Returns the read-only host display + stream status.
 *
 * Uses apiGetRaw because the backend endpoint returns the Pydantic model
 * directly (not wrapped in the ApiResponse {success, data} envelope).
 */
export function fetchHostDisplayStatus(): Promise<import("./types").HostDisplayStatus> {
  return apiGetRaw<import("./types").HostDisplayStatus>("/host-display/status");
}
