// ─── Task 4 — Unified Button Enable/Disable Rules ─────────────────────────
// Centralized helpers for consistent button state management across
// admin, seat, and display views.
//
// Three-layer model:
//   meetingStatus — meeting lifecycle (no_meeting / meeting_created / meeting_active / meeting_ended)
//   voteStatus    — vote state (none / open / closed)
//   uiPhase       — local admin UI phase (general / agenda_discussion)
//
// voteStatus=open/closed is NOT a meeting phase.
// uiPhase is frontend-only, never sent to backend.

import type { Meeting } from "../api/types";

// ── Derived Status Types ───────────────────────────────────────────────────

export type MeetingLifecycleStatus =
  | "no_meeting"
  | "meeting_created"
  | "meeting_active"
  | "meeting_ended";

export type VoteState = "none" | "open" | "closed";

// ── Status Derivation Helpers ──────────────────────────────────────────────

/**
 * Derive meeting lifecycle status for admin dashboard.
 *
 * @param meeting     - The active meeting from the hook (null if none active)
 * @param pendingMeeting - Locally-tracked pending meeting (just created, not started)
 * @param isEndedMeeting - Whether viewing an ended meeting's results
 */
export function deriveMeetingLifecycleStatus(
  meeting: Meeting | null,
  pendingMeeting: Meeting | null,
  isEndedMeeting: boolean,
): MeetingLifecycleStatus {
  if (isEndedMeeting) return "meeting_ended";
  if (pendingMeeting) return "meeting_created";
  if (meeting && meeting.status === "active") return "meeting_active";
  return "no_meeting";
}

/**
 * Derive meeting lifecycle status for seat view (simpler — only active or not).
 */
export function deriveSeatMeetingStatus(
  meeting: Meeting | null,
): "no_meeting" | "meeting_active" {
  if (!meeting || meeting.status !== "active") return "no_meeting";
  return "meeting_active";
}

/** Derive vote state for admin from hasActiveVote and any closed vote results. */
export function deriveAdminVoteState(
  hasActiveVote: boolean,
  voteResults?: ReadonlyArray<{ status: string }>,
): VoteState {
  if (hasActiveVote) return "open";
  if (voteResults && voteResults.some((v) => v.status === "closed")) return "closed";
  return "none";
}

/** Derive vote state for seat from the active vote's status. */
export function deriveSeatVoteState(
  activeVote: { status: string } | null,
): VoteState {
  if (!activeVote) return "none";
  return activeVote.status === "open" ? "open" : "closed";
}

// ── Admin Button Rules ─────────────────────────────────────────────────────

/** Create Pending Meeting — only when no meeting or ended, title non-empty, not busy. */
export function canCreateMeeting(
  status: MeetingLifecycleStatus,
  titleEmpty: boolean,
  busy: boolean,
): boolean {
  if (status !== "no_meeting" && status !== "meeting_ended") return false;
  return !titleEmpty && !busy;
}

/** Start Meeting — only when meeting_created (pending), has pending meeting, not busy. */
export function canStartMeeting(
  status: MeetingLifecycleStatus,
  hasPendingMeeting: boolean,
  busy: boolean,
): boolean {
  return status === "meeting_created" && hasPendingMeeting && !busy;
}

/** End Meeting — only when meeting is active and not busy. */
export function canEndMeeting(
  status: MeetingLifecycleStatus,
  busy: boolean,
): boolean {
  return status === "meeting_active" && !busy;
}

/** Phase selector — only when meeting is active. */
export function canUsePhaseSelector(status: MeetingLifecycleStatus): boolean {
  return status === "meeting_active";
}

/** Create Vote — only when meeting active, no open vote, not busy. */
export function canCreateVote(
  status: MeetingLifecycleStatus,
  voteState: VoteState,
  busy: boolean,
): boolean {
  return status === "meeting_active" && voteState !== "open" && !busy;
}

/** Close Vote — only when meeting active, vote is open, not busy. */
export function canCloseVote(
  status: MeetingLifecycleStatus,
  voteState: VoteState,
  busy: boolean,
): boolean {
  return status === "meeting_active" && voteState === "open" && !busy;
}

/** Set / Clear Speaker — only when meeting active. */
export function canControlSpeaker(status: MeetingLifecycleStatus): boolean {
  return status === "meeting_active";
}

/** Add / Delete Attendee — only when meeting active. */
export function canManageAttendees(status: MeetingLifecycleStatus): boolean {
  return status === "meeting_active";
}

/** Add / Delete Agenda — only when meeting active. */
export function canManageAgenda(status: MeetingLifecycleStatus): boolean {
  return status === "meeting_active";
}

/** Resolve service call — only when meeting active and the call is pending. */
export function canResolveServiceCall(
  status: MeetingLifecycleStatus,
  isPending: boolean,
): boolean {
  return status === "meeting_active" && isPending;
}

// ── Seat Button Rules ──────────────────────────────────────────────────────

/** Confirm Check-in — only in active meeting, seat occupied unchecked, attendee selected, WS connected. */
export function canCheckIn(
  status: "no_meeting" | "meeting_active",
  isOccupiedUnchecked: boolean,
  hasSelectedAttendee: boolean,
  wsConnected: boolean,
): boolean {
  return status === "meeting_active" && isOccupiedUnchecked && hasSelectedAttendee && wsConnected;
}

/** Demo Occupy Seat — only in active meeting, seat vacant, WS connected. */
export function canOccupySeat(
  status: "no_meeting" | "meeting_active",
  isVacant: boolean,
  wsConnected: boolean,
): boolean {
  return status === "meeting_active" && isVacant && wsConnected;
}

/** Demo Vacate Seat — only in active meeting, seat non-vacant, WS connected. */
export function canVacateSeat(
  status: "no_meeting" | "meeting_active",
  nonVacant: boolean,
  wsConnected: boolean,
): boolean {
  return status === "meeting_active" && nonVacant && wsConnected;
}

/** Submit / Update Vote — only in active meeting, vote open, checked in, option selected, WS connected. */
export function canSubmitVote(
  status: "no_meeting" | "meeting_active",
  voteStatus: "open" | "closed",
  isCheckedIn: boolean,
  hasSelectedOption: boolean,
  wsConnected: boolean,
): boolean {
  return status === "meeting_active" && voteStatus === "open" && isCheckedIn && hasSelectedOption && wsConnected;
}

/** Select Vote Option (clickable) — only in active meeting, vote open, WS connected. */
export function canSelectVoteOption(
  status: "no_meeting" | "meeting_active",
  voteStatus: "open" | "closed",
  wsConnected: boolean,
): boolean {
  return status === "meeting_active" && voteStatus === "open" && wsConnected;
}

/** Call Service — only in active meeting, checked in, no pending service, WS connected. */
export function canCallService(
  status: "no_meeting" | "meeting_active",
  isCheckedIn: boolean,
  hasPendingService: boolean,
  wsConnected: boolean,
): boolean {
  return status === "meeting_active" && isCheckedIn && !hasPendingService && wsConnected;
}

/** Cancel Service — only in active meeting, has pending service, WS connected. */
export function canCancelService(
  status: "no_meeting" | "meeting_active",
  hasPendingService: boolean,
  wsConnected: boolean,
): boolean {
  return status === "meeting_active" && hasPendingService && wsConnected;
}

/** Start Speech — only in active meeting, speaker seat, checked in, WS connected, models ready, mic supported. */
export function canStartSpeech(
  status: "no_meeting" | "meeting_active",
  isSpeaker: boolean,
  isCheckedIn: boolean,
  wsConnected: boolean,
  modelsReady: boolean,
  browserSupportsMic: boolean,
): boolean {
  return status === "meeting_active" && isSpeaker && isCheckedIn && wsConnected && modelsReady && browserSupportsMic;
}
