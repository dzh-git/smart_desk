import { Mic, User, UserCheck } from "lucide-react";
import type { SeatDisplay } from "../types";

// ── Helpers ─────────────────────────────────────────────────────────────────

function initials(name: string) {
  return name
    .split(" ")
    .slice(0, 2)
    .map((n) => n[0])
    .join("");
}

const avatarColors = [
  "bg-sky-600",
  "bg-teal-600",
  "bg-rose-600",
  "bg-amber-600",
  "bg-emerald-600",
  "bg-cyan-700",
  "bg-blue-700",
  "bg-orange-600",
  "bg-slate-600",
  "bg-green-700",
];

// ── Seat Card ───────────────────────────────────────────────────────────────

interface SeatCardProps {
  seat: SeatDisplay;
  isCurrentSpeaker: boolean;
  size?: "sm" | "md";
}

export function SeatCard({
  seat,
  isCurrentSpeaker,
  size = "md",
}: SeatCardProps) {
  const isSm = size === "sm";
  const hasAttendee = !!seat.attendeeName;

  const borderStyle = isCurrentSpeaker
    ? "ring-2 ring-emerald-400 shadow-emerald-100 shadow-lg"
    : seat.isVacant
      ? "border-dashed border-slate-300 bg-slate-50"
      : seat.isCheckedIn
        ? "border-slate-200 bg-white"
        : "border-slate-200 bg-amber-50/50"; // occupied_unchecked

  return (
    <div
      className={`relative rounded-xl border transition-all duration-300 ${borderStyle} ${
        isSm ? "p-2.5" : "p-3.5"
      }`}
    >
      {/* Speaker mic badge */}
      {isCurrentSpeaker && (
        <div className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-emerald-500 border-2 border-white flex items-center justify-center z-10">
          <Mic size={8} className="text-white" />
        </div>
      )}

      <div className="flex items-center gap-2.5">
        {/* Avatar */}
        <div className="flex-shrink-0 relative">
          {hasAttendee ? (
            <div
              className={`rounded-full flex items-center justify-center text-white font-semibold ${
                avatarColors[(seat.seatId - 1) % avatarColors.length]
              } ${isSm ? "w-8 h-8 text-xs" : "w-10 h-10 text-sm"}`}
            >
              {initials(seat.attendeeName!)}
            </div>
          ) : (
            <div
              className={`rounded-full bg-slate-200 flex items-center justify-center ${
                isSm ? "w-8 h-8" : "w-10 h-10"
              }`}
            >
              <User size={isSm ? 14 : 16} className="text-slate-400" />
            </div>
          )}
        </div>

        {/* Info */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span
              className={`font-bold text-slate-500 ${isSm ? "text-xs" : "text-xs"}`}
            >
              {seat.seatId}
            </span>
            {isCurrentSpeaker && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            )}
            {!isCurrentSpeaker && hasAttendee && seat.isCheckedIn && (
              <UserCheck size={10} className="text-sky-400" />
            )}
          </div>
          {hasAttendee ? (
            <>
              <p
                className={`font-semibold text-slate-800 leading-tight truncate ${isSm ? "text-xs" : "text-sm"}`}
              >
                {seat.attendeeName}
              </p>
              <p
                className={`text-slate-500 truncate ${isSm ? "text-[10px]" : "text-xs"}`}
              >
                {seat.attendeeTitle}
              </p>
            </>
          ) : (
            <p className={`text-slate-400 ${isSm ? "text-xs" : "text-sm"}`}>
              {seat.isVacant ? "Vacant" : "Occupied"}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Conference Table ────────────────────────────────────────────────────────

interface ConferenceTableProps {
  seats: SeatDisplay[];
  currentSpeaker: number | null;
  activeSeat?: number;
  onSeatClick?: (seatId: number) => void;
}

export function ConferenceTable({
  seats,
  currentSpeaker,
  activeSeat,
  onSeatClick,
}: ConferenceTableProps) {
  // Top row: seats 1-5, bottom row: seats 6-10 reversed for visual layout
  const topSeats = seats.slice(0, 5);
  const bottomSeats = [...seats.slice(5, 10)].reverse();

  return (
    <div className="flex flex-col gap-4 select-none">
      {/* Top row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {topSeats.map((seat) => (
          <button
            key={seat.seatId}
            onClick={() => onSeatClick?.(seat.seatId)}
            className={`text-left transition-transform lg:hover:scale-[1.02] active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 rounded-xl ${
              activeSeat === seat.seatId
                ? "ring-2 ring-sky-400 ring-offset-1"
                : ""
            }`}
          >
            <SeatCard
              seat={seat}
              isCurrentSpeaker={currentSpeaker === seat.seatId}
            />
          </button>
        ))}
      </div>

      {/* Table surface */}
      <div className="relative flex items-center justify-center py-6">
        <div className="w-full rounded-2xl bg-gradient-to-b from-stone-100 to-stone-200 border border-stone-300 shadow-inner h-24 flex items-center justify-center">
          <div className="text-center">
            <p className="text-xs font-semibold text-stone-500 tracking-widest uppercase">
              Conference Table
            </p>
          </div>
        </div>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {bottomSeats.map((seat) => (
          <button
            key={seat.seatId}
            onClick={() => onSeatClick?.(seat.seatId)}
            className={`text-left transition-transform lg:hover:scale-[1.02] active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 rounded-xl ${
              activeSeat === seat.seatId
                ? "ring-2 ring-sky-400 ring-offset-1"
                : ""
            }`}
          >
            <SeatCard
              seat={seat}
              isCurrentSpeaker={currentSpeaker === seat.seatId}
            />
          </button>
        ))}
      </div>
    </div>
  );
}
