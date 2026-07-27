import { useEffect, useState } from "react";
import {
  Activity,
  Armchair,
  Cpu,
  Tablet,
  Wifi,
  WifiOff,
} from "lucide-react";
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
  device_type?: string;
  device_id?: string | null;
  firmware_version?: string | null;
  last_heartbeat_at?: number | null;
  sensor_ok?: boolean | null;
}

interface TabletStatus {
  seat_id: number;
  provisioned: boolean;
  device_id: string | null;
  enabled: boolean;
  online: boolean;
  last_heartbeat_at: string | null;
  heartbeat_age_seconds: number | null;
  app_version: string | null;
  camera_status: string | null;
  face_model_status: string | null;
  registered_templates_count: number | null;
  microphone_status: string | null;
  meeting_websocket_status: string | null;
  diagnostic_status: string | null;
  last_error: string | null;
}

interface HardwareStatusData {
  deploy_mode?: string;
  seats: SeatStatus[];
  tablets?: TabletStatus[];
  tablet_offline_timeout_seconds?: number;
  integrated: boolean;
  gesture: {
    enabled: boolean;
    status_ws_url: string;
    online: boolean;
  };
}

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

const STATUS_LABELS: Record<string, string> = {
  READY: "就绪",
  ERROR: "错误",
  UNKNOWN: "未知",
  CONNECTED: "已连接",
  CONNECTING: "连接中",
  DISCONNECTED: "未连接",
};

function modeLabel(mode: string): string {
  return MODE_LABELS[mode] ?? mode;
}

function statusLabel(status: string | null): string {
  return status ? (STATUS_LABELS[status] ?? status) : "未上报";
}

function statusClass(status: string | null): string {
  if (status === "READY" || status === "CONNECTED") {
    return "text-techGreen";
  }
  if (status === "ERROR" || status === "DISCONNECTED") {
    return "text-techRose";
  }
  return "text-techMuted";
}

function formatLastSeen(value: string | number | null | undefined): string {
  if (value == null) return "从未";
  const timestamp =
    typeof value === "number" ? value * 1000 : Date.parse(value);
  if (!Number.isFinite(timestamp)) return "未知";
  return new Date(timestamp).toLocaleString();
}

/**
 * Read-only device operations panel.
 *
 * Tablet state comes from authenticated heartbeats persisted by the backend;
 * controller state comes from SeatGateway/Arduino managers. The two channels
 * remain deliberately separate even though they are grouped by seat.
 */
export function HardwareStatus() {
  const [data, setData] = useState<HardwareStatusData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = () => {
      apiGet<HardwareStatusData>("/hardware/status")
        .then((next) => {
          if (!active) return;
          setData(next);
          setError(null);
        })
        .catch((reason: unknown) => {
          if (!active) return;
          setError(
            reason instanceof Error ? reason.message : String(reason),
          );
        });
    };
    load();
    const timer = window.setInterval(load, 3_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!data) {
    return (
      <div className="bg-techCard border border-techBorder rounded-lg px-4 py-3 text-xs text-techMuted">
        {error ? `设备状态读取失败: ${error}` : "正在读取设备状态…"}
      </div>
    );
  }

  const { seats, gesture, deploy_mode } = data;
  const tablets = data.tablets ?? [];
  const seatIds = Array.from(
    new Set([
      ...tablets.map((item) => item.seat_id),
      ...seats.map((item) => item.seat_id),
    ]),
  ).sort((left, right) => left - right);

  return (
    <div className="bg-techCard border border-techBorder rounded-lg px-4 py-3 space-y-3">
      <div className="flex items-center gap-2">
        <Activity size={14} className="text-techCyan" />
        <span className="text-xs font-semibold uppercase tracking-wider text-techMuted">
          设备状态 / DEVICES
        </span>
        {deploy_mode && (
          <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-techBorder/60 text-techMuted">
            {deploy_mode === "esp32"
              ? "ESP32 直连"
              : deploy_mode === "distributed"
                ? "分布式兼容"
                : "单机兼容"}
          </span>
        )}
      </div>

      <div className="space-y-2">
        {seatIds.length === 0 && (
          <div className="text-xs text-techMuted">未配置席位设备</div>
        )}
        {seatIds.map((seatId) => {
          const tablet = tablets.find((item) => item.seat_id === seatId);
          const controller = seats.find((item) => item.seat_id === seatId);
          return (
            <section
              key={seatId}
              className="rounded border border-techBorder/80 p-2 space-y-2"
              aria-label={`席位 ${seatId} 设备状态`}
            >
              <div className="flex items-center gap-1.5 text-xs font-semibold text-techText">
                <Armchair size={13} className="text-techMuted" />
                席位 {seatId}
              </div>

              <div className="text-[11px] space-y-1">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-techText">
                    <Tablet size={13} className="text-techMuted" />
                    Android 平板
                    {tablet?.device_id && (
                      <span className="text-techMuted">
                        {tablet.device_id}
                      </span>
                    )}
                  </span>
                  {!tablet?.provisioned ? (
                    <span className="text-techMuted">未配置</span>
                  ) : !tablet.enabled ? (
                    <span className="text-techMuted">已禁用</span>
                  ) : tablet.online ? (
                    <span className="inline-flex items-center gap-1 text-techGreen">
                      <Wifi size={12} />
                      在线
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-techRose">
                      <WifiOff size={12} />
                      离线
                    </span>
                  )}
                </div>

                {tablet?.provisioned && (
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1 pl-5 text-techMuted">
                    <span>
                      摄像头：
                      <b className={statusClass(tablet.camera_status)}>
                        {statusLabel(tablet.camera_status)}
                      </b>
                    </span>
                    <span>
                      人脸模型：
                      <b className={statusClass(tablet.face_model_status)}>
                        {statusLabel(tablet.face_model_status)}
                      </b>
                    </span>
                    <span>
                      模板：{tablet.registered_templates_count ?? "—"}
                    </span>
                    <span>
                      麦克风：
                      <b className={statusClass(tablet.microphone_status)}>
                        {statusLabel(tablet.microphone_status)}
                      </b>
                    </span>
                    <span>
                      会议 WS：
                      <b
                        className={statusClass(
                          tablet.meeting_websocket_status,
                        )}
                      >
                        {statusLabel(tablet.meeting_websocket_status)}
                      </b>
                    </span>
                    <span>App：{tablet.app_version ?? "—"}</span>
                    <span className="col-span-2">
                      最近心跳：
                      {formatLastSeen(tablet.last_heartbeat_at)}
                    </span>
                    {tablet.last_error && (
                      <span className="col-span-2 text-techRose break-all">
                        最近错误：{tablet.last_error}
                      </span>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between text-[11px] border-t border-techBorder/60 pt-1.5">
                <span className="flex items-center gap-1.5 text-techText">
                  <Cpu size={13} className="text-techMuted" />
                  {controller?.device_type === "esp32"
                    ? "ESP32 席位控制器"
                    : "兼容席位控制器"}
                  {controller?.device_id && (
                    <span className="text-techMuted">
                      {controller.device_id}
                    </span>
                  )}
                </span>
                {!controller ? (
                  <span className="text-techMuted">未配置</span>
                ) : !controller.enabled ? (
                  <span className="text-techMuted">已禁用</span>
                ) : controller.connected ? (
                  <span className="text-techGreen">
                    在线 · {modeLabel(controller.current_mode)}
                    {controller.command_pending &&
                      ` → ${modeLabel(controller.intended_mode)}`}
                  </span>
                ) : (
                  <span className="text-techRose">离线</span>
                )}
              </div>
              {controller && (
                <div className="pl-5 text-[10px] text-techMuted flex flex-wrap gap-x-3">
                  <span>
                    固件：{controller.firmware_version ?? "—"}
                  </span>
                  <span>
                    心跳：
                    {formatLastSeen(controller.last_heartbeat_at)}
                  </span>
                  <span>
                    传感器：
                    {controller.sensor_ok == null
                      ? "未上报"
                      : controller.sensor_ok
                        ? "正常"
                        : "错误"}
                  </span>
                  {controller.last_error && (
                    <span className="text-techRose">
                      最近错误：{controller.last_error}
                    </span>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>

      <div className="flex items-center justify-between text-xs border-t border-techBorder pt-2">
        <span className="flex items-center gap-1.5 text-techText">
          <Cpu size={13} className="text-techMuted" />
          手势服务
        </span>
        {!gesture.enabled ? (
          <span className="text-techMuted">已禁用</span>
        ) : gesture.online ? (
          <span className="inline-flex items-center gap-1 text-techGreen">
            <Wifi size={13} />
            在线
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-techRose">
            <WifiOff size={13} />
            离线
          </span>
        )}
      </div>
    </div>
  );
}
