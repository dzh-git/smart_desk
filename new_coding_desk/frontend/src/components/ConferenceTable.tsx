import { Mic, User, UserCheck, Clock } from "lucide-react";
import type { SeatDisplay } from "../types";

// ── Seat Status ───────────────────────────────────────────────────────────────

type SeatStatus = "speaking" | "checked_in" | "waiting" | "vacant";

function deriveSeatStatus(
  seat: SeatDisplay,
  isCurrentSpeaker: boolean,
): SeatStatus {
  if (isCurrentSpeaker) return "speaking";
  if (seat.isVacant) return "vacant";
  if (seat.isCheckedIn) return "checked_in";
  return "waiting";
}

// ── Seat Status Visual Tokens ─────────────────────────────────────────────────

interface StatusVisual {
  container: string;
  text: string;
  dot: string;
  icon: React.ReactNode;
  labelCn: string;
  labelEn: string;
}

const statusVisuals: Record<SeatStatus, StatusVisual> = {
  speaking: {
    container:
      "border-techCyan/60 bg-techCyan/10 shadow-cyan-glow",
    text: "text-techCyan",
    dot: "bg-techCyan",
    icon: <Mic size={12} className="text-techCyan" />,
    labelCn: "发言中",
    labelEn: "Speaking",
  },
  checked_in: {
    container: "border-techGreen/40 bg-techGreen/10",
    text: "text-techGreen",
    dot: "bg-techGreen",
    icon: <UserCheck size={12} className="text-techGreen" />,
    labelCn: "已签到",
    labelEn: "Checked In",
  },
  waiting: {
    container: "border-techAmber/40 bg-techAmber/10",
    text: "text-techAmber",
    dot: "bg-techAmber",
    icon: <Clock size={12} className="text-techAmber" />,
    labelCn: "待签到",
    labelEn: "Waiting",
  },
  vacant: {
    container: "border-techBorder bg-techSurface",
    text: "text-techMuted",
    dot: "bg-techMuted",
    icon: <User size={12} className="text-techMuted" />,
    labelCn: "空座",
    labelEn: "Vacant",
  },
};

// ── Seat Visual Node ──────────────────────────────────────────────────────────

interface SeatVisualNodeProps {
  seatId: number;
  name?: string | null;
  status: SeatStatus;
  selected?: boolean;
  onClick?: () => void;
}

function SeatVisualNode({
  seatId,
  name,
  status,
  selected,
  onClick,
}: SeatVisualNodeProps) {
  const sv = statusVisuals[status];
  const isSpeaking = status === "speaking";

  return (
    <button
      type="button"
      onClick={onClick}
      className={`
        flex flex-col items-center justify-center gap-1
        min-w-[96px] min-h-[80px]
        rounded-xl border transition-all duration-200
        ${sv.container}
        ${isSpeaking ? "animate-pulse" : ""}
        ${
          selected && !isSpeaking
            ? "ring-2 ring-techCyan/50"
            : selected && isSpeaking
              ? ""
              : ""
        }
        hover:brightness-125 active:scale-95
        focus:outline-none focus-visible:ring-2 focus-visible:ring-techCyan
        cursor-pointer
      `}
    >
      {/* Seat number + speaking indicator */}
      <div className="flex items-center gap-1.5">
        <span
          className={`text-[10px] font-bold uppercase tracking-widest ${sv.text}`}
        >
          SEAT {seatId}
        </span>
        {isSpeaking && (
          <span className="w-1.5 h-1.5 rounded-full bg-techCyan animate-pulse" />
        )}
      </div>

      {/* Attendee name or vacant label */}
      {name ? (
        <span
          className={`text-xs font-semibold leading-tight text-center px-1 max-w-[88px] truncate ${sv.text}`}
        >
          {name}
        </span>
      ) : (
        <span className="text-xs text-techMuted">空座</span>
      )}

      {/* Status badge row */}
      <div className="flex items-center gap-1 mt-0.5">
        {sv.icon}
        <span className="text-[10px] font-medium leading-none text-techMuted/80">
          {sv.labelCn}
        </span>
        <span className="text-[8px] font-mono uppercase tracking-wider text-techMuted/40 leading-none">
          {sv.labelEn}
        </span>
      </div>
    </button>
  );
}

// ── Table Legend ──────────────────────────────────────────────────────────────

function TableLegend() {
  const items: { status: SeatStatus }[] = [
    { status: "speaking" },
    { status: "checked_in" },
    { status: "waiting" },
    { status: "vacant" },
  ];

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1.5">
      {items.map(({ status }) => {
        const sv = statusVisuals[status];
        return (
          <div key={status} className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${sv.dot}`} />
            <span className="text-[11px] font-medium text-techMuted">
              {sv.labelCn}
            </span>
            <span className="text-[9px] font-mono uppercase tracking-wider text-techMuted/50">
              {sv.labelEn}
            </span>
          </div>
        );
      })}
      {/* Selected indicator */}
      <div className="flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full border border-techCyan bg-transparent" />
        <span className="text-[11px] font-medium text-techMuted">选中</span>
        <span className="text-[9px] font-mono uppercase tracking-wider text-techMuted/50">
          Selected
        </span>
      </div>
    </div>
  );
}

// ── Conference Table ──────────────────────────────────────────────────────────

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
    <div className="flex flex-col gap-5 select-none">
      {/* Legend */}
      <TableLegend />

      {/* Top row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {topSeats.map((seat) => {
          const isSpeaker = currentSpeaker === seat.seatId;
          const status = deriveSeatStatus(seat, isSpeaker);
          return (
            <SeatVisualNode
              key={seat.seatId}
              seatId={seat.seatId}
              name={seat.attendeeName}
              status={status}
              selected={activeSeat === seat.seatId}
              onClick={() => onSeatClick?.(seat.seatId)}
            />
          );
        })}
      </div>

      {/* Central table surface */}
      <div className="relative flex items-center justify-center py-4">
        <div
          className="
            w-full max-w-[420px]
            rounded-[2rem]
            bg-techSurface
            border border-techBorder
            shadow-cyan-glow
            bg-tech-radial
            h-28
            flex items-center justify-center
            overflow-hidden
          "
        >
          <div className="text-center space-y-1">
            <p className="text-sm font-bold text-techText tracking-wider">
              SmartDesk
            </p>
            <p className="text-[10px] font-medium text-techMuted tracking-[0.2em] uppercase">
              会议桌 / Meeting Table
            </p>
            <div className="flex items-center justify-center gap-1.5 mt-1">
              <span className="w-1.5 h-1.5 rounded-full bg-techGreen animate-pulse" />
              <span className="text-[10px] font-semibold text-techGreen tracking-wide">
                会议中
              </span>
              <span className="text-[8px] font-mono uppercase tracking-wider text-techGreen/60">
                Active Meeting
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {bottomSeats.map((seat) => {
          const isSpeaker = currentSpeaker === seat.seatId;
          const status = deriveSeatStatus(seat, isSpeaker);
          return (
            <SeatVisualNode
              key={seat.seatId}
              seatId={seat.seatId}
              name={seat.attendeeName}
              status={status}
              selected={activeSeat === seat.seatId}
              onClick={() => onSeatClick?.(seat.seatId)}
            />
          );
        })}
      </div>
    </div>
  );
}
