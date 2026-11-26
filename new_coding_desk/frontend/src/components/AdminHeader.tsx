import { Cpu, WifiOff } from "lucide-react";
import { ActionButton, isDemoControlsEnabled } from "./shared";
import type { ConnectionStatus } from "../types";

interface AdminHeaderProps {
  title: string;
  meetingStatus: string;
  connection: ConnectionStatus;
  onModeSwitch?: () => void;
  previewSeat?: number;
}

export function AdminHeader({
  title,
  meetingStatus,
  connection,
  onModeSwitch,
  previewSeat,
}: AdminHeaderProps) {
  const meetingLabel = meetingStatus === "active" ? "进行中"
    : meetingStatus === "finished" ? "已结束" : "待开始";
  return (
    <header className="desk-hero host-header">
      <div className="host-header__identity">
        <span className="desk-brand-mark"><Cpu size={18} aria-hidden="true" /></span>
        <div className="min-w-0">
          <p>SmartDesk 主持人控制台</p>
          <h1>{title || "等待会议 / Waiting for Meeting"}</h1>
        </div>
      </div>
      <div className="host-header__status">
        {isDemoControlsEnabled() && <span className="host-demo-label">演示模式 / Demo Mode</span>}
        <span className="host-meeting-status" data-live={meetingStatus === "active"}>{meetingLabel}</span>
        {connection === "connecting" && <span role="status">正在连接</span>}
        {connection === "disconnected" && meetingStatus === "active" && (
          <span className="host-offline" aria-label="连接中断"><WifiOff size={17} aria-hidden="true" /></span>
        )}
        {onModeSwitch && previewSeat != null && (
          <ActionButton variant="secondary" size="sm" onClick={onModeSwitch}>
            预览座位 {previewSeat} / Preview Seat {previewSeat}
          </ActionButton>
        )}
      </div>
    </header>
  );
}
