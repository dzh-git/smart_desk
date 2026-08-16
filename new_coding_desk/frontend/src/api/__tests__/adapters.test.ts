import { describe, it, expect } from "vitest";
import { buildSeatDisplays } from "../adapters";
import type { SeatState, Attendee, SpeakerSeat } from "../types";

describe("buildSeatDisplays", () => {
  it("always returns exactly 9 seats", () => {
    const result = buildSeatDisplays([], [], null);
    expect(result).toHaveLength(9);
  });

  it("treats missing seat states as vacant", () => {
    const result = buildSeatDisplays([], [], null);
    expect(result.every((s) => s.isVacant)).toBe(true);
    expect(result.every((s) => s.isCheckedIn)).toBe(false);
    expect(result.every((s) => s.attendeeName === null)).toBe(true);
  });

  it("correctly maps attendee to seat via attendee_id", () => {
    const states: SeatState[] = [
      {
        seat_id: 1,
        status: "checked_in",
        attendee_id: 5,
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];
    const attendees: Attendee[] = [
      { id: 5, meeting_id: 1, name: "Alice", title: "CEO", assigned_seat_id: 1, seat_id: 1, checked_in: true },
    ];

    const result = buildSeatDisplays(states, attendees, null);
    expect(result[0].attendeeName).toBe("Alice");
    expect(result[0].attendeeTitle).toBe("CEO");
    expect(result[0].isCheckedIn).toBe(true);
    expect(result[0].isVacant).toBe(false);
  });

  it("marks speaker seat as independent highlight (not a seat state)", () => {
    const states: SeatState[] = [
      {
        seat_id: 3,
        status: "checked_in",
        attendee_id: 7,
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];
    const attendees: Attendee[] = [
      { id: 7, meeting_id: 1, name: "Bob", title: "CFO", assigned_seat_id: 3, seat_id: 3, checked_in: true },
    ];
    const speaker: SpeakerSeat = { seat_id: 3 };

    const result = buildSeatDisplays(states, attendees, speaker);
    expect(result[2].isSpeaker).toBe(true);
    expect(result[2].isCheckedIn).toBe(true); // speaker does not override check-in
    expect(result[2].isVacant).toBe(false);

    // Other seats should not be marked as speaker
    expect(result[0].isSpeaker).toBe(false);
    expect(result[1].isSpeaker).toBe(false);
    expect(result[4].isSpeaker).toBe(false);
  });

  it("handles occupied_unchecked seats correctly", () => {
    const states: SeatState[] = [
      {
        seat_id: 2,
        status: "occupied_unchecked",
        attendee_id: null,
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];

    const result = buildSeatDisplays(states, [], null);
    expect(result[1].isVacant).toBe(false);
    expect(result[1].isCheckedIn).toBe(false);
    expect(result[1].isSpeaker).toBe(false);
    expect(result[1].attendeeName).toBeNull();
  });

  it("maps multiple seats with correct IDs 1-9", () => {
    const states: SeatState[] = Array.from({ length: 9 }, (_, i) => ({
      seat_id: i + 1,
      status: "checked_in" as const,
      attendee_id: i + 1,
      updated_at: "2026-01-01T00:00:00Z",
    }));
    const attendees: Attendee[] = Array.from({ length: 9 }, (_, i) => ({
      id: i + 1,
      meeting_id: 1,
      name: `Person ${i + 1}`,
      title: "Member",
      assigned_seat_id: i + 1,
      seat_id: i + 1,
      checked_in: true,
    }));

    const result = buildSeatDisplays(states, attendees, null);
    expect(result).toHaveLength(9);
    for (let i = 0; i < 9; i++) {
      expect(result[i].seatId).toBe(i + 1);
      expect(result[i].attendeeName).toBe(`Person ${i + 1}`);
      expect(result[i].isCheckedIn).toBe(true);
    }
  });

  it("treats null speakerSeat as no speaker", () => {
    const states: SeatState[] = [
      {
        seat_id: 5,
        status: "checked_in",
        attendee_id: 7,
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];
    const attendees: Attendee[] = [
      { id: 7, meeting_id: 1, name: "Bob", title: "CFO", assigned_seat_id: 5, seat_id: 5, checked_in: true },
    ];
    const speaker: SpeakerSeat = { seat_id: null };

    const result = buildSeatDisplays(states, attendees, speaker);
    expect(result.every((s) => s.isSpeaker)).toBe(false);
  });
});
