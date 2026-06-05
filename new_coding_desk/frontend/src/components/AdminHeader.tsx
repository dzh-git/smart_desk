import { Clock, Cpu } from "lucide-react";
import {
  ConnectionBadge,
  MeetingStatusBadge,
  useClock,
  formatTime,
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
}

export function AdminHeader({
  title,
  meetingStatus,
  connection,
  onModeSwitch,
  previewSeat,
}: AdminHeaderProps) {
  const now = useClock();

  return (
    <header className="bg-slate-900 text-white px-6 py-4 flex items-center justify-between shadow-lg flex-shrink-0">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-sky-500 flex items-center justify-center">
            <Cpu size={16} className="text-white" />
          </div>
          <span className="text-sm font-bold tracking-tight text-white">
            SmartDesk
          </span>
        </div>
        <div className="w-px h-6 bg-slate-700" />
        <div>
          <p className="text-sm font-semibold text-white leading-tight">
            {title || "No active meeting"}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <MeetingStatusBadge status={meetingStatus} />
        <ConnectionBadge status={connection} />
        <div className="flex items-center gap-1.5 text-sm font-mono text-slate-300">
          <Clock size={13} />
          {formatTime(now)}
        </div>
        {onModeSwitch && previewSeat != null && (
          <div className="w-px h-6 bg-slate-700" />
        )}
        {onModeSwitch && previewSeat != null && (
          <button
            onClick={onModeSwitch}
            className="flex items-center gap-2 text-xs font-medium bg-slate-800 border border-slate-700 hover:bg-slate-700 transition-colors rounded-lg px-3 py-1.5 text-slate-300"
          >
            <span className="w-2 h-2 rounded-full bg-sky-400" />
            Seat {previewSeat} Preview
          </button>
        )}
      </div>
    </header>
  );
}
