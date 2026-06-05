import React from "react";
import { Wifi, WifiOff, Loader2 } from "lucide-react";
import type { ConnectionStatus } from "../types";

// ── Environment Helpers ──────────────────────────────────────────────────────

/** Returns true when VITE_ENABLE_DEMO_CONTROLS is set to "true". */
export function isDemoControlsEnabled(): boolean {
  try {
    return (
      typeof import.meta !== "undefined" &&
      import.meta.env?.VITE_ENABLE_DEMO_CONTROLS === "true"
    );
  } catch {
    return false;
  }
}

// ── Connection Badge ───────────────────────────────────────────────────────

interface ConnectionBadgeProps {
  status: ConnectionStatus;
  className?: string;
}

export function ConnectionBadge({ status, className = "" }: ConnectionBadgeProps) {
  if (status === "connected") {
    return (
      <span
        className={`inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2.5 py-1 ${className}`}
      >
        <Wifi size={12} />
        Connected
      </span>
    );
  }
  if (status === "connecting") {
    return (
      <span
        className={`inline-flex items-center gap-1.5 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-1 ${className}`}
      >
        <Loader2 size={12} className="animate-spin" />
        Connecting
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium text-red-700 bg-red-50 border border-red-200 rounded-full px-2.5 py-1 ${className}`}
    >
      <WifiOff size={12} />
      Disconnected
    </span>
  );
}

// ── Meeting Status Badge ────────────────────────────────────────────────────
// Consumes API-returned status: "pending" | "active" | "finished"

interface MeetingStatusBadgeProps {
  status: string;
}

export function MeetingStatusBadge({ status }: MeetingStatusBadgeProps) {
  const configs: Record<
    string,
    { label: string; classes: string; dot: string }
  > = {
    active: {
      label: "In Progress",
      classes:
        "text-emerald-700 bg-emerald-50 border-emerald-200",
      dot: "bg-emerald-500 animate-pulse",
    },
    pending: {
      label: "Pending",
      classes: "text-amber-700 bg-amber-50 border-amber-200",
      dot: "bg-amber-500",
    },
    finished: {
      label: "Ended",
      classes: "text-slate-600 bg-slate-50 border-slate-200",
      dot: "bg-slate-400",
    },
  };
  const cfg =
    configs[status] ?? {
      label: status,
      classes: "text-sky-700 bg-sky-50 border-sky-200",
      dot: "bg-sky-500",
    };
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-semibold border rounded-full px-2.5 py-1 ${cfg.classes}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

// ── Clock ───────────────────────────────────────────────────────────────────

export function useClock() {
  const [now, setNow] = React.useState(new Date());
  React.useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export function formatTime(date: Date) {
  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

export function formatDuration(ms: number) {
  const m = Math.floor(ms / 60000);
  const h = Math.floor(m / 60);
  const rem = m % 60;
  if (h > 0) return `${h}h ${rem}m`;
  return `${m}m`;
}

export function timeAgo(date: Date) {
  const diff = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

// ── Empty State ─────────────────────────────────────────────────────────────

interface EmptyStateProps {
  icon: React.ReactNode;
  title: string;
  description?: string;
}

export function EmptyState({ icon, title, description }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-center">
      <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-3">
        {icon}
      </div>
      <p className="text-sm font-medium text-slate-600">{title}</p>
      {description && (
        <p className="text-xs text-slate-400 mt-1 max-w-xs">{description}</p>
      )}
    </div>
  );
}

// ── Loading State ───────────────────────────────────────────────────────────

interface LoadingStateProps {
  rows?: number;
}

export function LoadingState({ rows = 3 }: LoadingStateProps) {
  return (
    <div className="space-y-3 animate-pulse">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-slate-200 flex-shrink-0" />
          <div className="flex-1 space-y-2 pt-1">
            <div className="h-3 bg-slate-200 rounded w-3/4" />
            <div className="h-2.5 bg-slate-100 rounded w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Disconnected Overlay ────────────────────────────────────────────────────

interface DisconnectedOverlayProps {
  onRetry?: () => void;
}

export function DisconnectedOverlay({ onRetry }: DisconnectedOverlayProps) {
  return (
    <div className="absolute inset-0 bg-white/80 backdrop-blur-sm flex flex-col items-center justify-center z-50 rounded-xl">
      <div className="w-14 h-14 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mb-4">
        <WifiOff className="text-red-500" size={24} />
      </div>
      <p className="text-sm font-semibold text-slate-800 mb-1">
        Connection Lost
      </p>
      <p className="text-xs text-slate-500 mb-4">Attempting to reconnect...</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="text-xs font-medium text-sky-600 border border-sky-200 rounded-full px-4 py-1.5 hover:bg-sky-50 transition-colors"
        >
          Retry Now
        </button>
      )}
    </div>
  );
}

// ── Section Card ────────────────────────────────────────────────────────────

interface SectionCardProps {
  title: string;
  children: React.ReactNode;
  className?: string;
  headerRight?: React.ReactNode;
}

export function SectionCard({
  title,
  children,
  className = "",
  headerRight,
}: SectionCardProps) {
  return (
    <div
      className={`bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden ${className}`}
    >
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          {title}
        </h3>
        {headerRight}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}
