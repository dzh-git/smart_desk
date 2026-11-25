import React from "react";
import { Wifi, WifiOff, Loader2 } from "lucide-react";
import type { ConnectionStatus } from "../types";

// ── Environment Helpers ──────────────────────────────────────────────────────

/** Browser demo mode. The environment flag also supports the Windows launcher. */
export function isDemoControlsEnabled(): boolean {
  return import.meta.env.MODE === "demo" || import.meta.env.VITE_ENABLE_DEMO_CONTROLS === "true";
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
  const totalSeconds = Math.floor(ms / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/**
 * Parse a backend datetime string that may be a naive UTC timestamp.
 *
 * Backend uses `datetime.utcnow()` which Pydantic serialises without
 * timezone info (e.g. "2026-01-01T04:27:00").  `new Date(value)` would
 * treat this as LOCAL time, causing an incorrect display (e.g. 8 hours
 * off for UTC+8 users).
 *
 * - null / undefined / empty string → null
 * - Strings with "Z" or ±HH:MM offset → parsed as-is
 * - Strings WITHOUT timezone → treated as UTC ("Z" appended)
 * - Invalid values → null
 */
export function parseBackendDate(value: string | null | undefined): Date | null {
  if (value == null || value === "") return null;

  // Already has timezone info:  "Z", "+08:00", "-05:00"
  if (/[Zz]|[+-]\d{2}:\d{2}$/.test(value)) {
    const d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }

  // Naive datetime — treat as UTC by appending "Z"
  const d = new Date(value + "Z");
  return isNaN(d.getTime()) ? null : d;
}

export function formatTranscriptTime(value: string | null | undefined): string {
  const d = parseBackendDate(value);
  if (!d) return "--:--";
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
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
      <div className="w-12 h-12 rounded-full bg-techCardSoft flex items-center justify-center text-techMuted mb-3">
        {icon}
      </div>
      <p className="text-sm font-medium text-techText">{title}</p>
      {description && (
        <p className="text-xs text-techMuted mt-1 max-w-xs">{description}</p>
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
          <div className="w-8 h-8 rounded-full bg-techCardSoft flex-shrink-0" />
          <div className="flex-1 space-y-2 pt-1">
            <div className="h-3 bg-techCardSoft rounded w-3/4" />
            <div className="h-2.5 bg-techBorder rounded w-1/2" />
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
    <div className="absolute inset-0 bg-techBg/80 backdrop-blur-sm flex flex-col items-center justify-center z-50 rounded-xl">
      <div className="w-14 h-14 rounded-full bg-techRose/10 border-2 border-techRose/30 flex items-center justify-center mb-4">
        <WifiOff className="text-techRose" size={24} />
      </div>
      <p className="text-sm font-semibold text-techText mb-1">
        Connection Lost
      </p>
      <p className="text-xs text-techMuted mb-4">Attempting to reconnect...</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="text-xs font-medium border border-techCyan/30 rounded-full px-4 py-1.5 text-techCyan hover:bg-techCyan/10 transition-colors"
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
  titleEn?: string;
  children: React.ReactNode;
  className?: string;
  headerRight?: React.ReactNode;
}

export function SectionCard({
  title,
  titleEn,
  children,
  className = "",
  headerRight,
}: SectionCardProps) {
  return (
    <div
      className={`desk-panel overflow-hidden ${className}`}
    >
      <div className="flex min-h-12 items-center justify-between gap-3 border-b border-techBorder px-4 py-3 sm:px-5">
        {titleEn ? (
          <h3 className="inline-flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-sm font-semibold text-techText">
              {title}
            </span>
            <span className="desk-label">
              {titleEn}
            </span>
          </h3>
        ) : (
          <h3 className="text-sm font-semibold text-techText">
            {title}
          </h3>
        )}
        {headerRight}
      </div>
      <div className="p-4 sm:p-5">{children}</div>
    </div>
  );
}

// ==========================================
// SECTION: SMARTDESK VISUAL ATOMS
// DualLabel, StatusBadge, ActionButton
// ==========================================

/** Concatenate class names, filtering falsy values. */
function cx(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(" ");
}

// ── DualLabel ─────────────────────────────────────────────────────────────

interface DualLabelProps {
  cn: string;
  en?: string;
  className?: string;
  cnClassName?: string;
  enClassName?: string;
}

export function DualLabel({
  cn,
  en,
  className,
  cnClassName,
  enClassName,
}: DualLabelProps) {
  return (
    <span className={cx("inline-flex items-baseline gap-1.5", className)}>
      <span className={cx("font-semibold text-techText", cnClassName)}>
        {cn}
      </span>
      {en && (
        <span
          className={cx(
            "text-xs font-mono uppercase tracking-wider text-techMuted",
            enClassName,
          )}
        >
          {en}
        </span>
      )}
    </span>
  );
}

// ── StatusBadge ───────────────────────────────────────────────────────────

interface StatusBadgeProps {
  status:
    | "online"
    | "speaking"
    | "waiting"
    | "offline"
    | "success"
    | "warning"
    | "danger"
    | "neutral";
  labelCn: string;
  labelEn?: string;
  icon?: React.ReactNode;
  className?: string;
  pulse?: boolean;
}

const statusBadgeStyles: Record<string, { container: string; dot: string }> = {
  speaking: { container: "text-techCyan border-techCyan", dot: "bg-techCyan" },
  online: { container: "text-techGreen border-techGreen", dot: "bg-techGreen" },
  success: { container: "text-techGreen border-techGreen", dot: "bg-techGreen" },
  waiting: { container: "text-techAmber border-techAmber", dot: "bg-techAmber" },
  warning: { container: "text-techAmber border-techAmber", dot: "bg-techAmber" },
  offline: { container: "text-techMuted border-techBorder", dot: "bg-techMuted" },
  neutral: { container: "text-techMuted border-techBorder", dot: "bg-techMuted" },
  danger: { container: "text-techRose border-techRose", dot: "bg-techRose" },
};

export function StatusBadge({
  status,
  labelCn,
  labelEn,
  icon,
  className,
  pulse,
}: StatusBadgeProps) {
  const style = statusBadgeStyles[status] ?? statusBadgeStyles.neutral;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 text-xs font-medium border rounded-full px-2.5 py-1",
        style.container,
        pulse && status === "speaking" && "shadow-cyan-glow",
        className,
      )}
    >
      <span
        className={cx(
          "w-1.5 h-1.5 rounded-full",
          style.dot,
          pulse && "animate-pulse",
        )}
      />
      {icon && <span className="shrink-0">{icon}</span>}
      <span>{labelCn}</span>
      {labelEn && (
        <span className="text-[0.7rem] font-mono uppercase tracking-wider opacity-60">
          {labelEn}
        </span>
      )}
    </span>
  );
}

// ── ActionButton ──────────────────────────────────────────────────────────

interface ActionButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "success" | "warning" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  touch?: boolean;
  icon?: React.ReactNode;
  loading?: boolean;
  children: React.ReactNode;
}

const actionButtonVariants: Record<string, string> = {
  primary:
    "bg-techCyan text-techBg hover:brightness-110 active:brightness-90",
  secondary:
    "bg-techCard border border-techBorder text-techText hover:bg-techCardSoft",
  success:
    "bg-techGreen text-techBg hover:brightness-110 active:brightness-90",
  warning:
    "bg-techAmber text-techBg hover:brightness-110 active:brightness-90",
  danger: "bg-techRose text-techBg hover:brightness-110 active:brightness-90",
  ghost: "bg-transparent text-techText hover:bg-techCard",
};

const actionButtonSizes: Record<string, string> = {
  sm: "text-xs px-3 py-1.5 min-h-[32px]",
  md: "text-sm px-4 py-2 min-h-[40px]",
  lg: "text-base px-5 py-2.5 min-h-[48px]",
};

export function ActionButton({
  variant = "primary",
  size = "md",
  touch = false,
  icon,
  loading = false,
  children,
  className,
  disabled,
  ...rest
}: ActionButtonProps) {
  const isDisabled = disabled || loading;
  const variantClass =
    actionButtonVariants[variant] ?? actionButtonVariants.primary;
  const sizeClass = actionButtonSizes[size] ?? actionButtonSizes.md;
  const heightClass = touch ? "min-h-[44px]" : undefined;

  return (
    <button
      type="button"
      className={cx(
        "inline-flex items-center justify-center gap-2 font-medium rounded-lg",
        "transition-all duration-150 active:scale-95",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-techCyan",
        variantClass,
        sizeClass,
        heightClass,
        isDisabled && "opacity-40 cursor-not-allowed",
        className,
      )}
      disabled={isDisabled}
      {...rest}
    >
      {loading ? (
        <Loader2
          size={size === "sm" ? 14 : size === "lg" ? 18 : 16}
          className="animate-spin shrink-0"
        />
      ) : icon ? (
        <span className="shrink-0">{icon}</span>
      ) : null}
      {children}
    </button>
  );
}

// ==========================================
// SECTION: SMARTDESK VISUAL CARDS
// PanelCard, MetricTile, TechEmptyState
// ==========================================

// ── PanelCard ─────────────────────────────────────────────────────────────

interface PanelCardProps {
  titleCn?: string;
  titleEn?: string;
  icon?: React.ReactNode;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  variant?: "default" | "active" | "success" | "warning" | "danger";
}

const panelCardVariants: Record<string, string> = {
  default: "border-techBorder",
  active: "border-techCyan shadow-cyan-glow",
  success: "border-techGreen",
  warning: "border-techAmber",
  danger: "border-techRose",
};

export function PanelCard({
  titleCn,
  titleEn,
  icon,
  headerRight,
  children,
  className,
  bodyClassName,
  variant = "default",
}: PanelCardProps) {
  const hasHeader = titleCn || titleEn || icon || headerRight;
  const borderClass =
    panelCardVariants[variant] ?? panelCardVariants.default;

  return (
    <div
      className={cx(
        "desk-panel overflow-hidden",
        borderClass,
        className,
      )}
    >
      {hasHeader && (
        <div className="flex min-h-12 items-center justify-between gap-3 border-b border-techBorder px-4 py-3 sm:px-5">
          <div className="flex min-w-0 items-center gap-2">
            {icon && (
              <span className="shrink-0 text-techCyan">{icon}</span>
            )}
            {(titleCn || titleEn) && (
              <span className="inline-flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                {titleCn && (
                  <span className="text-sm font-semibold text-techText">
                    {titleCn}
                  </span>
                )}
                {titleEn && (
                  <span className="desk-label">
                    {titleEn}
                  </span>
                )}
              </span>
            )}
          </div>
          {headerRight && (
            <div className="shrink-0">{headerRight}</div>
          )}
        </div>
      )}
      <div className={cx("p-4", bodyClassName)}>{children}</div>
    </div>
  );
}

// ── MetricTile ───────────────────────────────────────────────────────────

interface MetricTileProps {
  labelCn: string;
  labelEn?: string;
  value: React.ReactNode;
  subtext?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: "default" | "cyan" | "success" | "warning" | "danger" | "muted";
  className?: string;
}

const metricTileTones: Record<string, string> = {
  default: "text-techText",
  cyan: "text-techCyan",
  success: "text-techGreen",
  warning: "text-techAmber",
  danger: "text-techRose",
  muted: "text-techMuted",
};

export function MetricTile({
  labelCn,
  labelEn,
  value,
  subtext,
  icon,
  tone = "default",
  className,
}: MetricTileProps) {
  return (
    <div
      className={cx(
        "bg-techCard border border-techBorder rounded-lg p-4",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1 min-w-0">
          <div className="inline-flex items-baseline gap-1.5">
            <span className="text-xs font-medium text-techMuted">
              {labelCn}
            </span>
            {labelEn && (
              <span className="text-[0.65rem] font-mono uppercase tracking-wider text-techMuted">
                {labelEn}
              </span>
            )}
          </div>
          <div
            className={cx(
              "text-2xl font-bold",
              metricTileTones[tone] ?? metricTileTones.default,
            )}
          >
            {value}
          </div>
          {subtext && (
            <div className="text-xs text-techMuted">{subtext}</div>
          )}
        </div>
        {icon && <div className="text-techMuted shrink-0">{icon}</div>}
      </div>
    </div>
  );
}

// ── SectionHeader ────────────────────────────────────────────────────────

interface SectionHeaderProps {
  titleCn: string;
  titleEn?: string;
  icon?: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
}

export function SectionHeader({
  titleCn,
  titleEn,
  icon,
  right,
  className,
}: SectionHeaderProps) {
  return (
    <div className={cx("flex items-center justify-between", className)}>
      <div className="flex items-center gap-2 min-w-0">
        {icon && <span className="text-techCyan shrink-0">{icon}</span>}
        <span className="inline-flex items-baseline gap-1.5 truncate">
          <span className="text-sm font-semibold text-techText truncate">
            {titleCn}
          </span>
          {titleEn && (
            <span className="text-[0.65rem] font-mono uppercase tracking-wider text-techMuted truncate">
              {titleEn}
            </span>
          )}
        </span>
      </div>
      {right && <div className="shrink-0 ml-2">{right}</div>}
    </div>
  );
}

// ── TechEmptyState ───────────────────────────────────────────────────────

interface TechEmptyStateProps {
  icon?: React.ReactNode;
  titleCn: string;
  titleEn?: string;
  descriptionCn?: string;
  descriptionEn?: string;
  action?: React.ReactNode;
  className?: string;
}

export function TechEmptyState({
  icon,
  titleCn,
  titleEn,
  descriptionCn,
  descriptionEn,
  action,
  className,
}: TechEmptyStateProps) {
  return (
    <div
      className={cx(
        "flex flex-col items-center justify-center py-16 px-6 text-center",
        className,
      )}
    >
      {icon && (
        <div className="w-14 h-14 rounded-full bg-techCardSoft border border-techBorder flex items-center justify-center text-techMuted mb-4">
          {icon}
        </div>
      )}
      <span className="inline-flex items-baseline gap-1.5 mb-2">
        <span className="text-lg font-semibold text-techText">
          {titleCn}
        </span>
        {titleEn && (
          <span className="text-xs font-mono uppercase tracking-wider text-techMuted">
            {titleEn}
          </span>
        )}
      </span>
      {(descriptionCn || descriptionEn) && (
        <p className="text-sm text-techMuted max-w-sm">
          {descriptionCn}
          {descriptionEn && (
            <span className="block text-[0.65rem] font-mono uppercase tracking-wider mt-0.5 opacity-60">
              {descriptionEn}
            </span>
          )}
        </p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
