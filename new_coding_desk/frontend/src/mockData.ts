// ─── Visual fixture / Storybook seed data ───────────────────────────────────
// Kept for testing and visual reference. Not used in production.
// This file is NOT imported by App.tsx or any production component.

import type { SeatDisplay } from "./types";

export const FIXTURE_SEAT_DISPLAYS: SeatDisplay[] = Array.from(
  { length: 10 },
  (_, i) => ({
    seatId: i + 1,
    attendeeName: i < 6 ? `Person ${i + 1}` : null,
    attendeeTitle: i < 6 ? "Board Member" : null,
    attendeeId: i < 6 ? i + 1 : null,
    isCheckedIn: i < 4,
    isVacant: i >= 6,
    isSpeaker: i === 2,
  }),
);
