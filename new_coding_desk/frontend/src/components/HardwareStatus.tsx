import { useEffect, useState } from "react";
import { Cpu, Wifi, WifiOff, Activity, Armchair } from "lucide-react";
import { apiGet } from "../api/client";

interface SeatStatus {
  seat_id: number;
  enabled: boolean;
  connected: boolean;
  port: string | null;
  current_mode: string;
  intended_mode: string;
  command_pending: boolean;
  last_ack_at: number | null;
  last_error: string | null;
}

interface HardwareStatusData {
  deploy_mode?: string;
  seats: SeatStatus[];
  integrated: boolean;
  gesture: {
    enabled: boolean;
    status_ws_url: string;
    online: boolean;
  };
}

// Human-readable Chinese labels for the firmware lighting modes.
const MODE_LABELS: Record<string, string> = {
  IDLE: "待机",
  WELCOME: "迎宾",
  MEETING_ACTIVE: "会议中",
  MEETING_ENDED: "会议结束",
  AGENDA_ACTIVE: "议程",
  VOTE_OPEN: "投票中",
  SERVICE_CALL: "服务呼叫",
  AI_SPEAKING: "发言识别中",
  VOTE_CLOSED: "投票结束",
  UNKNOWN: "等待确认",
  BOOT: "启动",
  ERROR: "错误",
  OFF: "关闭",
};

function modeLabel(mode: string): string {
  return MODE_LABELS[mode] ?? mode;
}

/**
 * Hardware status panel (Phase 5, per-seat).
 *
 * Polls GET /api/hardware/status every 3s and shows, for each seat, the
 * Arduino lighting-controller state (online/offline + current light mode),
 * plus the gesture service status. Always renders even when the backend is
 * unreachable (shows the last known / error state).
 */
export function HardwareStatus() {
  const [data, setData] = useState<HardwareStatusData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () => {
      apiGet<HardwareStatusData>("/hardware/status")
        .then((d) => {
          if (!active) return;
          setData(d);
          setError(null);
        })
        .catch((e: unknown) => {
          if (!active) return;
          setError(e instanceof Error ? e.message : String(e));
        });
    };
    load();
    const timer = setInterval(load, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  if (!data) {
    return (
      <div className="bg-techCard border border-techBorder rounded-lg px-4 py-3 text-xs text-techMuted">
        {error ? `硬件状态读取失败: ${error}` : "正在读取硬件状态…"}
      </div>
    );
  }

  const { seats, gesture, deploy_mode } = data;

  return (
    <div className="bg-techCard border border-techBorder rounded-lg px-4 py-3 space-y-2">
      <div className="flex items-center gap-2">
        <Activity size={14} className="text-techCyan" />
        <span className="text-xs font-semibold uppercase tracking-wider text-techMuted">
          硬件状态 / HARDWARE
        </span>
        {deploy_mode && (
          <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-techBorder/60 text-techMuted">
            {deploy_mode === "distributed" ? "分布式" : "单机"}
          </span>
        )}
      </div>

      {/* Per-seat LED controller status */}
      <div className="space-y-1">
        {seats.length === 0 && (
          <div className="text-xs text-techMuted">未配置座位灯控</div>
        )}
        {seats.map((s) => (
          <div
            key={s.seat_id}
            className="flex items-center justify-between text-xs"
          >
            <span className="flex items-center gap-1.5 text-techText">
              <Armchair size={13} className="text-techMuted" />
              座位 {s.seat_id}
              <span className="text-techMuted/60">{s.port ?? "网络"}</span>
            </span>
            {!s.enabled ? (
              <span className="text-techMuted">已禁用</span>
            ) : s.connected ? (
              <span className="inline-flex items-center gap-1 text-techGreen">
                <span className="w-2 h-2 rounded-full bg-techGreen animate-pulse" />
                {modeLabel(s.current_mode)}
                {s.command_pending && ` → ${modeLabel(s.intended_mode)}`}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-techRose">
                <span className="w-2 h-2 rounded-full bg-techRose" />
                离线
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Gesture service */}
      <div className="flex items-center justify-between text-xs border-t border-techBorder pt-2">
        <span className="flex items-center gap-1.5 text-techText">
          <Cpu size={13} className="text-techMuted" />
          手势服务
        </span>
        {!gesture.enabled ? (
          <span className="text-techMuted">已禁用</span>
        ) : gesture.online ? (
          <span className="inline-flex items-center gap-1 text-techGreen">
            <Wifi size={13} className="text-techGreen" />
            在线
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-techRose">
            <WifiOff size={13} className="text-techRose" />
            离线
          </span>
        )}
      </div>
    </div>
  );
}
