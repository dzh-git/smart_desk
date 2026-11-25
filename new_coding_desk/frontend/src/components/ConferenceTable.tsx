import { Mic, User, UserCheck, Clock } from "lucide-react";
import type { SeatDisplay } from "../types";

// ── Seat Status ───────────────────────────────────────────────────────────────

type SeatStatus = "speaking" | "checked_in" | "waiting" | "vacant";

function deriveSeatStatus(
  seat: SeatDisplay,
  isCurrentSpeaker: boolean,
): SeatStatus {
  if (seat.isVacant) return "vacant";
  if (isCurrentSpeaker && seat.isCheckedIn) return "speaking";
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
    container: "border-techCyan/60 bg-techCardSoft shadow-cyan-glow",
    text: "text-techCyan",
    dot: "bg-techCyan",
    icon: <Mic size={12} className="text-techCyan" />,
    labelCn: "发言中",
    labelEn: "Speaking",
  },
  checked_in: {
    container: "border-techGreen/30 bg-techCard",
    text: "text-techGreen",
    dot: "bg-techGreen",
    icon: <UserCheck size={12} className="text-techGreen" />,
    labelCn: "已签到",
    labelEn: "Checked In",
  },
  waiting: {
    container: "border-techAmber/35 bg-techCard",
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
  isHostSeat?: boolean;
}

function SeatVisualNode({
  seatId,
  name,
  status,
  selected,
  onClick,
  isHostSeat = false,
}: SeatVisualNodeProps) {
  const sv = statusVisuals[status];
  const isSpeaking = status === "speaking";

  return (
    <button
      type="button"
      data-testid={`conference-seat-${seatId}`}
      aria-pressed={Boolean(selected)}
      onClick={onClick}
      className={`
        flex min-w-0 w-full flex-col items-center justify-center gap-1.5 px-1.5 py-2
        ${isHostSeat ? "min-h-[100px]" : "min-h-[76px]"}
        rounded-xl border transition-colors duration-150
        ${sv.container}
        ${selected ? "ring-1 ring-techCyan" : ""}
        hover:border-techCyan hover:bg-techCardSoft
        focus:outline-none focus-visible:ring-2 focus-visible:ring-techCyan
        cursor-pointer
      `}
    >
      {/* Seat number + speaking indicator */}
      <div className="flex items-center gap-1.5">
        <span
          className={`whitespace-nowrap font-mono text-[11px] font-semibold tracking-wider ${sv.text}`}
        >
          SEAT {seatId}
        </span>
        {isSpeaking && (
          <span className="size-1.5 rounded-full bg-techCyan motion-safe:animate-pulse" />
        )}
      </div>
      {isHostSeat && (
        <span className="flex flex-col items-center text-[11px] font-semibold text-techCyan">
          主持人席
          <span className="font-mono text-[9px] uppercase tracking-wider text-techMuted">
            Host Seat
          </span>
        </span>
      )}

      {/* Attendee name or vacant label */}
      {name ? (
        <span
          className="w-full truncate text-center text-sm font-semibold leading-tight text-techText"
          title={name}
        >
          {name}
        </span>
      ) : status !== "vacant" ? (
        <span className="text-xs text-techMuted">空座</span>
      ) : null}

      {/* Status badge row */}
      <div className="flex flex-wrap items-center justify-center gap-x-1 gap-y-0.5">
        {sv.icon}
        <span className="text-[10px] font-medium leading-none text-techMuted">
          {sv.labelCn}
        </span>
        <span className="conference-table__seat-status-en font-mono text-[9px] uppercase leading-none text-techMuted">
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
    <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5">
      {items.map(({ status }) => {
        const sv = statusVisuals[status];
        return (
          <div key={status} className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${sv.dot}`} />
            <span className="text-[11px] font-medium text-techMuted">
              {sv.labelCn}
            </span>
            <span className="font-mono text-[9px] uppercase tracking-wider text-techMuted">
              {sv.labelEn}
            </span>
          </div>
        );
      })}
      {/* Selected indicator */}
      <div className="flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full border border-techCyan bg-transparent" />
        <span className="text-[11px] font-medium text-techMuted">选中</span>
        <span className="font-mono text-[9px] uppercase tracking-wider text-techMuted">
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
  preparing?: boolean;
  onSeatClick?: (seatId: number) => void;
}

export function ConferenceTable({
  seats,
  currentSpeaker,
  activeSeat,
  preparing = false,
  onSeatClick,
}: ConferenceTableProps) {
  const hostSeat = seats.find((seat) => seat.seatId === 1);
  const topSeats = seats.filter((seat) => seat.seatId >= 2 && seat.seatId <= 5);
  const bottomSeats = seats.filter(
    (seat) => seat.seatId >= 6 && seat.seatId <= 9,
  );
  const speakerSeat = preparing ? null : currentSpeaker;
  const statusColor = preparing
    ? "border-techAmber/30 text-techAmber"
    : "border-techGreen/30 text-techGreen";

  return (
    <div className="conference-table flex select-none flex-col gap-4">
      <div className="conference-table__layout">
        <div
          data-testid="conference-host-edge"
          className="conference-table__host"
        >
          {hostSeat && (
            <SeatVisualNode
              seatId={hostSeat.seatId}
              name={hostSeat.attendeeName}
              status={deriveSeatStatus(hostSeat, speakerSeat === 1)}
              selected={activeSeat === hostSeat.seatId}
              onClick={() => onSeatClick?.(hostSeat.seatId)}
              isHostSeat
            />
          )}
        </div>

        <div data-testid="conference-top-edge" className="conference-table__north">
          {topSeats.map((seat) => (
            <SeatVisualNode
              key={seat.seatId}
              seatId={seat.seatId}
              name={seat.attendeeName}
              status={deriveSeatStatus(seat, speakerSeat === seat.seatId)}
              selected={activeSeat === seat.seatId}
              onClick={() => onSeatClick?.(seat.seatId)}
            />
          ))}
        </div>

        <div className="conference-table__surface">
          <div className="relative min-w-0 px-2 py-4 text-center sm:px-4">
            <p className="text-[clamp(0.8125rem,4.25cqi,1.25rem)] font-semibold text-techText">
              SmartDesk 会议桌
            </p>
            <p className="desk-label mt-1">Smart Conference Table</p>
            <div
              className={`mt-2 inline-flex max-w-full flex-wrap items-center justify-center gap-x-1.5 gap-y-0.5 rounded-full border bg-techBg/70 px-2.5 py-1 ${statusColor}`}
            >
              <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
              <span className="text-xs font-semibold">
                {preparing ? "待开始" : "会议中"}
              </span>
              <span className="text-[9px] font-mono uppercase tracking-wider">
                {preparing ? "Pending" : "Active Meeting"}
              </span>
            </div>
          </div>
        </div>

        <div data-testid="conference-bottom-edge" className="conference-table__south">
          {bottomSeats.map((seat) => (
            <SeatVisualNode
              key={seat.seatId}
              seatId={seat.seatId}
              name={seat.attendeeName}
              status={deriveSeatStatus(seat, speakerSeat === seat.seatId)}
              selected={activeSeat === seat.seatId}
              onClick={() => onSeatClick?.(seat.seatId)}
            />
          ))}
        </div>
      </div>
      <TableLegend />
    </div>
  );
}
