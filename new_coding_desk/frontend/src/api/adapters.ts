// ─── Seat Display Adapter ─────────────────────────────────────────────────
// Synthesizes SeatState + Attendee[] + SpeakerSeat into UI-ready ViewModels.
// The adapter always produces exactly 9 seat entries.

import type { SeatState, Attendee, SpeakerSeat } from "./types";
import type { SeatDisplay } from "../types";

const SEAT_COUNT = 9;

/**
 * Build 9 seat display rows from the raw API responses.
 *
 * Rules applied:
 * - Speaker seat is a separate highlight (isSpeaker), not mixed into status.
 * - Missing seat_states entries are treated as vacant.
 * - Attendees are matched to seats via attendee_id.
 */
export function buildSeatDisplays(
  seatStates: SeatState[],
  attendees: Attendee[],
  speakerSeat: SpeakerSeat | null,
): SeatDisplay[] {
  // Index attendees by id for O(1) lookup
  const attendeeById = new Map<number, Attendee>();
  for (const a of attendees) {
    attendeeById.set(a.id, a);
  }

  // Index seat states by seat_id
  const stateBySeat = new Map<number, SeatState>();
  for (const s of seatStates) {
    stateBySeat.set(s.seat_id, s);
  }

  const speakerSeatId = speakerSeat?.seat_id ?? null;

  const displays: SeatDisplay[] = [];

  for (let id = 1; id <= SEAT_COUNT; id++) {
    const state = stateBySeat.get(id);
    const attendee =
      state?.attendee_id != null
        ? attendeeById.get(state.attendee_id) ?? null
        : null;

    displays.push({
      seatId: id,
      attendeeName: attendee?.name ?? null,
      attendeeTitle: attendee?.title ?? null,
      attendeeId: state?.attendee_id ?? null,
      isCheckedIn: state?.status === "checked_in",
      isVacant: state == null || state.status === "vacant",
      isSpeaker: speakerSeatId === id,
    });
  }

  return displays;
}
