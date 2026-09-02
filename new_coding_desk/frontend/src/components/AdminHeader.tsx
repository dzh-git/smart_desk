import { Clock, Cpu, Users, Mic, Timer, Wifi, WifiOff, Loader2 } from "lucide-react";
import {
  DualLabel,
  StatusBadge,
  ActionButton,
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
    <header className="bg-techBg border-b border-techBorder bg-tech-radial backdrop-blur-sm flex-shrink-0">
      <div className="px-3 sm:px-5 py-2.5">
        <div className="flex items-center justify-between gap-2">
          {/* ── Left Block: Brand + Meeting Title ── */}
          <div className="flex items-center gap-3 min-w-0 shrink-0 max-w-[45%]">
            <div className="w-8 h-8 rounded-lg bg-techCyan/20 flex items-center justify-center shrink-0">
              <Cpu size={16} className="text-techCyan" />
            </div>
            <div className="min-w-0">
              <DualLabel cn="SmartDesk 主持人控制台" en="HOST CONSOLE" />
              <p className="truncate text-sm font-semibold text-techText leading-tight">
                {title || "等待会议 / Waiting for Meeting"}
              </p>
            </div>
          </div>

          {/* ── Center Block: Status Pills ── */}
          <div className="flex items-center gap-1.5 flex-wrap justify-center min-w-0">
            {/* Meeting status badge */}
            <StatusBadge
              status={meetingBadge.status}
              labelCn={meetingBadge.labelCn}
              labelEn={meetingBadge.labelEn}
              pulse={meetingBadge.pulse}
            />

            {/* Connection status badge */}
            <StatusBadge
              status={connBadge.status}
              labelCn={connBadge.labelCn}
              labelEn={connBadge.labelEn}
              icon={connBadge.icon}
            />

            {/* Checked-in count */}
            {showMetrics && (
              <span className="inline-flex items-center gap-1 px-2 py-1 bg-techCard border border-techBorder rounded-md text-xs">
                <Users size={11} className="text-techGreen shrink-0" />
                <span className="text-techMuted">签到 / Check-in</span>
                <span className="font-semibold text-techGreen">{checkedInCount}</span>
                <span className="text-techBorder text-[10px]">/</span>
                <span className="font-semibold text-techMuted text-[10px]">{totalSeats}</span>
              </span>
            )}

            {/* Current speaker */}
            {showMetrics && speakerName && (
              <span className="inline-flex items-center gap-1 px-2 py-1 bg-techCard border border-techBorder rounded-md text-xs max-w-[170px]">
                <Mic size={11} className="text-techCyan shrink-0" />
                <span className="text-techMuted shrink-0">发言人 / Speaker</span>
                <span className="text-techMuted truncate">{speakerName}</span>
              </span>
            )}

            {/* Elapsed meeting time */}
            {showMetrics && elapsedMs != null && elapsedMs > 0 && (
              <span className="inline-flex items-center gap-1 px-2 py-1 bg-techCard border border-techBorder rounded-md text-xs">
                <Timer size={11} className="text-techCyan shrink-0" />
                <span className="text-techMuted">时长 / Time</span>
                <span className="font-semibold text-techText font-mono">
                  {formatDuration(elapsedMs)}
                </span>
              </span>
            )}

            {/* Pending requests */}
            {showMetrics && pendingRequestCount != null && pendingRequestCount > 0 && (
              <span className="inline-flex items-center gap-1 px-2 py-1 bg-techCard border border-techAmber/30 rounded-md text-xs">
                <span className="font-semibold text-techAmber">{pendingRequestCount}</span>
                <span className="text-techMuted">待处理 / Pending</span>
              </span>
            )}

            {/* Clock */}
            <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-mono text-techMuted">
              <Clock size={11} className="shrink-0" />
              {formatTime(now)}
            </span>
          </div>

          {/* ── Right Block: Action Buttons ── */}
          <div className="flex items-center gap-2 shrink-0">
            {onModeSwitch && previewSeat != null && (
              <>
                <div className="hidden sm:block w-px h-5 bg-techBorder" />
                <ActionButton
                  variant="secondary"
                  size="sm"
                  onClick={onModeSwitch}
                >
                  <span className="w-2 h-2 rounded-full bg-techCyan" />
                  预览座位 {previewSeat} / Preview Seat {previewSeat}
                </ActionButton>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
