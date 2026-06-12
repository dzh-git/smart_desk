import {
  Coffee,
  Droplets,
  Leaf,
  MoreHorizontal,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
} from "lucide-react";
import { SectionCard, EmptyState } from "./shared";
import type { ServiceCall, ServiceType } from "../api/types";

const typeConfig: Record<
  ServiceType,
  { label: string; icon: React.ReactNode; color: string }
> = {
  coffee: {
    label: "Coffee",
    icon: <Coffee size={14} />,
    color:
      "text-amber-700 bg-amber-50 border-amber-200",
  },
  tea: {
    label: "Tea",
    icon: <Leaf size={14} />,
    color:
      "text-green-700 bg-green-50 border-green-200",
  },
  water: {
    label: "Water",
    icon: <Droplets size={14} />,
    color:
      "text-sky-700 bg-sky-50 border-sky-200",
  },
  other: {
    label: "Other",
    icon: <MoreHorizontal size={14} />,
    color:
      "text-slate-700 bg-slate-50 border-slate-200",
  },
};

const statusLabel: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  pending: {
    label: "Pending",
    icon: <Clock size={12} />,
    color: "text-amber-600",
  },
  resolved: {
    label: "Resolved",
    icon: <CheckCircle2 size={12} />,
    color: "text-emerald-600",
  },
  cancelled: {
    label: "Cancelled",
    icon: <XCircle size={12} />,
    color: "text-slate-400",
  },
};

interface ServicePanelProps {
  calls: ServiceCall[];
  /** Mapping seat_id → attendee name */
  seatNameMap: Record<number, string>;
  /** Callback when admin resolves a pending call. */
  onResolve?: (callId: number) => void;
  /** True while a resolve operation is in flight. */
  resolvingId?: number | null;
}

export function ServicePanel({ calls, seatNameMap, onResolve, resolvingId }: ServicePanelProps) {
  const pending = calls.filter((c) => c.status === "pending");

  return (
    <SectionCard
      title="Service Requests"
      headerRight={
        pending.length > 0 ? (
          <span className="text-xs font-bold bg-rose-500 text-white rounded-full w-5 h-5 flex items-center justify-center">
            {pending.length}
          </span>
        ) : undefined
      }
    >
      {calls.length === 0 ? (
        <EmptyState
          icon={<CheckCircle2 size={20} />}
          title="All clear"
          description="No service requests."
        />
      ) : (
        <div className="space-y-2">
          {calls.map((call) => (
            <ServiceRow
              key={call.id}
              call={call}
              attendeeName={seatNameMap[call.seat_id] ?? `Seat ${call.seat_id}`}
              onResolve={onResolve ? () => onResolve(call.id) : undefined}
              isResolving={resolvingId === call.id}
            />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function ServiceRow({
  call,
  attendeeName,
  onResolve,
  isResolving,
}: {
  call: ServiceCall;
  attendeeName: string;
  onResolve?: () => void;
  isResolving?: boolean;
}) {
  const cfg = typeConfig[call.service_type] ?? typeConfig.other;
  const st = statusLabel[call.status] ?? statusLabel.pending;

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5">
      <div
        className={`flex items-center justify-center rounded-lg border w-8 h-8 flex-shrink-0 ${cfg.color}`}
      >
        {cfg.icon}
      </div>
      <div className="flex-1 min-w-0">
        <p className="truncate text-sm font-semibold text-slate-800 leading-tight">
          {cfg.label} — Seat {call.seat_id}
        </p>
        <p className="truncate text-xs text-slate-500 leading-tight mt-0.5 flex items-center gap-1">
          {attendeeName}
        </p>
      </div>
      <span
        className={`inline-flex shrink-0 items-center gap-1 text-xs font-medium ${st.color}`}
      >
        {st.icon}
        {st.label}
      </span>
      {call.status === "pending" && onResolve && (
        <button
          onClick={onResolve}
          disabled={isResolving}
          className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-emerald-600 bg-white border border-emerald-200 rounded-lg px-2.5 py-1 hover:bg-emerald-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isResolving ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <CheckCircle2 size={12} />
          )}
          Resolve
        </button>
      )}
    </div>
  );
}
