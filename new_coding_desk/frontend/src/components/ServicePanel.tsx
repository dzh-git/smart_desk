import {
  Coffee,
  Droplets,
  Leaf,
  MoreHorizontal,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { PanelCard, TechEmptyState, StatusBadge, ActionButton } from "./shared";
import type { ServiceCall, ServiceType } from "../api/types";

const typeConfig: Record<
  ServiceType,
  { label: string; labelCn: string; icon: React.ReactNode; color: string }
> = {
  coffee: {
    label: "Coffee",
    labelCn: "咖啡",
    icon: <Coffee size={14} />,
    color: "text-techCyan bg-techCardSoft border-techCyan/30",
  },
  tea: {
    label: "Tea",
    labelCn: "茶水",
    icon: <Leaf size={14} />,
    color: "text-techGreen bg-techCardSoft border-techGreen/30",
  },
  water: {
    label: "Water",
    labelCn: "饮用水",
    icon: <Droplets size={14} />,
    color: "text-techBlue bg-techCardSoft border-techBlue/30",
  },
  other: {
    label: "Other",
    labelCn: "其他",
    icon: <MoreHorizontal size={14} />,
    color: "text-techMuted bg-techCardSoft border-techBorder",
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
    <PanelCard
      titleCn="服务请求"
      titleEn="Service Requests"
      variant={pending.length > 0 ? "warning" : "default"}
      headerRight={
        pending.length > 0 ? (
          <span className="inline-flex items-center justify-center rounded-full bg-techRose/20 text-techRose text-[0.65rem] font-bold min-w-[20px] h-5 px-1.5">
            {pending.length}
          </span>
        ) : undefined
      }
    >
      {calls.length === 0 ? (
        <TechEmptyState
          icon={<CheckCircle2 size={20} />}
          titleCn="暂无请求"
          titleEn="No Requests"
          descriptionCn="座位端提交服务请求后将在此显示"
          descriptionEn="Service requests from seats appear here"
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
    </PanelCard>
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

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-techBorder bg-techCardSoft px-3 py-2.5">
      <div
        className={`flex items-center justify-center rounded-lg border w-8 h-8 flex-shrink-0 ${cfg.color}`}
      >
        {cfg.icon}
      </div>
      <div className="flex-1 min-w-0">
        <p className="truncate text-sm font-semibold text-techText leading-tight">
          {cfg.labelCn} / {cfg.label}
          <span className="font-normal text-techMuted"> — </span>
          Seat {call.seat_id}
        </p>
        <p className="truncate text-xs text-techMuted leading-tight mt-0.5">
          {attendeeName}
        </p>
      </div>

      {call.status === "pending" && (
        <StatusBadge status="warning" labelCn="待处理" labelEn="Pending" />
      )}
      {call.status === "resolved" && (
        <StatusBadge status="success" labelCn="已处理" labelEn="Resolved" />
      )}
      {call.status === "cancelled" && (
        <StatusBadge status="neutral" labelCn="已取消" labelEn="Cancelled" />
      )}

      {call.status === "pending" && onResolve && (
        <ActionButton
          variant="success"
          size="sm"
          icon={isResolving ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
          loading={isResolving}
          onClick={onResolve}
        >
          Resolve
        </ActionButton>
      )}
    </div>
  );
}
