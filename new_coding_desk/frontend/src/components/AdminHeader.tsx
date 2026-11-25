import { Clock, Cpu, Users, Mic, Timer, Wifi, WifiOff, Loader2 } from "lucide-react";
import {
  DualLabel,
  StatusBadge,
  ActionButton,
  isDemoControlsEnabled,
  useClock,
  formatTime,
  formatDuration,
} from "./shared";
import type { ConnectionStatus } from "../types";

interface AdminHeaderProps {
  /** Meeting title from the backend. */
  title: string;
  /** Meeting status from the backend: "pending" | "active" | "finished". */
  meetingStatus: string;
  /** WebSocket connection status. */
  connection: ConnectionStatus;
  /** Callback when "Seat N Preview" is clicked. */
  onModeSwitch?: () => void;
  /** Seat number being previewed. */
  previewSeat?: number;
  /** Number of attendees checked in (optional — shown when available). */
  checkedInCount?: number;
  /** Total number of seats configured (optional). */
  totalSeats?: number;
  /** The seat ID of the current speaker (optional). */
  speakerSeatId?: number | null;
  /** Display name of the current speaker (optional). */
  speakerName?: string | null;
  /** Milliseconds elapsed since meeting start (optional). */
  elapsedMs?: number;
  /** Number of pending service requests (optional). */
  pendingRequestCount?: number;
  /** Whether an active vote is in progress (optional). */
  hasActiveVote?: boolean;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

interface MeetingBadgeConfig {
  status: "online" | "waiting" | "offline" | "neutral";
  labelCn: string;
  labelEn: string;
  pulse: boolean;
}

function getMeetingBadge(status: string): MeetingBadgeConfig {
  switch (status) {
    case "active":
      return { status: "online", labelCn: "进行中", labelEn: "IN PROGRESS", pulse: true };
    case "pending":
      return { status: "waiting", labelCn: "待开始", labelEn: "PENDING", pulse: false };
    case "finished":
      return { status: "offline", labelCn: "已结束", labelEn: "ENDED", pulse: false };
    default:
      return { status: "neutral", labelCn: "状态未知", labelEn: "UNKNOWN", pulse: false };
  }
}

interface ConnectionBadgeConfig {
  status: "success" | "warning" | "danger";
  labelCn: string;
  labelEn: string;
  icon: React.ReactNode;
}

function getConnectionBadge(status: ConnectionStatus): ConnectionBadgeConfig {
  switch (status) {
    case "connected":
      return {
        status: "success",
        labelCn: "已连接",
        labelEn: "CONNECTED",
        icon: <Wifi size={12} />,
      };
    case "connecting":
      return {
        status: "warning",
        labelCn: "连接中",
        labelEn: "CONNECTING",
        icon: <Loader2 size={12} className="animate-spin" />,
      };
    case "disconnected":
      return {
        status: "danger",
        labelCn: "已断开",
        labelEn: "DISCONNECTED",
        icon: <WifiOff size={12} />,
      };
  }
}

// ── Component ───────────────────────────────────────────────────────────────

export function AdminHeader({
  title,
  meetingStatus,
  connection,
  onModeSwitch,
  previewSeat,
  checkedInCount,
  totalSeats,
  speakerSeatId: _speakerSeatId,
  speakerName,
  elapsedMs,
  pendingRequestCount,
  hasActiveVote: _hasActiveVote,
}: AdminHeaderProps) {
  const now = useClock();
  const meetingBadge = getMeetingBadge(meetingStatus);
  const connBadge = getConnectionBadge(connection);

  // Show compact metric pills only when we have actual meeting data
  const showMetrics =
    checkedInCount != null &&
    totalSeats != null &&
    (meetingStatus === "active" || meetingStatus === "pending");

  return (
    <header className="desk-hero shrink-0 border-b border-techBorder">
      <div className="mx-auto max-w-[1760px] px-4 pb-5 pt-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="desk-brand-mark">
              <Cpu size={20} aria-hidden="true" />
            </span>
            <DualLabel
              cn="SmartDesk 主持人控制台"
              en="HOST CONSOLE"
              className="min-w-0 flex-col gap-0.5"
              cnClassName="text-sm"
              enClassName="desk-label"
            />
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-2">
            {isDemoControlsEnabled() && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-techAmber/40 bg-techAmber/10 px-2.5 py-1 text-xs font-semibold text-techAmber">
                演示模式 / Demo Mode
              </span>
            )}
            <StatusBadge
              status={meetingBadge.status}
              labelCn={meetingBadge.labelCn}
              labelEn={meetingBadge.labelEn}
              pulse={meetingBadge.pulse}
              className="bg-techBg/65"
            />
            <StatusBadge
              status={connBadge.status}
              labelCn={connBadge.labelCn}
              labelEn={connBadge.labelEn}
              icon={connBadge.icon}
              className="bg-techBg/65"
            />
            <span className="inline-flex items-center gap-1.5 rounded-full border border-techBorder bg-techBg/65 px-2.5 py-1 font-mono text-xs tabular-nums text-techMuted">
              <Clock size={12} className="shrink-0" aria-hidden="true" />
              {formatTime(now)}
            </span>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <h1 className="min-w-0 max-w-full break-words text-[clamp(1.5rem,3vw,2.75rem)] font-semibold leading-tight tracking-[-0.035em] text-techText">
            {title || "等待会议 / Waiting for Meeting"}
          </h1>
          {onModeSwitch && previewSeat != null && (
            <ActionButton
              variant="secondary"
              size="sm"
              onClick={onModeSwitch}
              icon={<span className="block size-1.5 rounded-full bg-techCyan" />}
            >
              预览座位 {previewSeat} / Preview Seat {previewSeat}
            </ActionButton>
          )}
        </div>

        {showMetrics && (
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
            <span className="inline-flex items-center gap-1.5">
              <Users size={13} className="shrink-0 text-techCyan" aria-hidden="true" />
              <span className="text-techMuted">签到 / Check-in</span>
              <span className="font-semibold tabular-nums text-techText">
                {checkedInCount} / {totalSeats}
              </span>
            </span>
            {speakerName && (
              <span className="inline-flex min-w-0 items-center gap-1.5">
                <Mic size={13} className="shrink-0 text-techCyan" aria-hidden="true" />
                <span className="text-techMuted shrink-0">发言人 / Speaker</span>
                <span className="truncate font-medium text-techText">{speakerName}</span>
              </span>
            )}
            {elapsedMs != null && elapsedMs > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <Timer size={13} className="shrink-0 text-techCyan" aria-hidden="true" />
                <span className="text-techMuted">时长 / Time</span>
                <span className="font-mono font-semibold tabular-nums text-techText">
                  {formatDuration(elapsedMs)}
                </span>
              </span>
            )}
            {pendingRequestCount != null && pendingRequestCount > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <span className="font-semibold tabular-nums text-techAmber">{pendingRequestCount}</span>
                <span className="text-techMuted">待处理 / Pending</span>
              </span>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
