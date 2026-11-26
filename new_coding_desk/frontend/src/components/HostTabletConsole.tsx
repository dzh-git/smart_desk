import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, LockKeyhole, Mic, Settings, ShieldCheck, UserCheck, X } from "lucide-react";
import { AdminDashboard } from "./AdminDashboard";
import { SpeechControl } from "./SeatTablet";
import { debugAdmitSeat, identityCheckinSeat } from "../api/resources";
import { getNativeBridge } from "../native/NativeBridge";
import type {
  DeviceInfo,
  HostIdentityProfile,
} from "../native/NativeBridge";
import {
  subscribeNativeEvents,
  type NativeIdentityStatus,
  type SmartDeskNativeEvent,
} from "../native/nativeEvents";
import { useSeatData } from "../hooks/useSeatData";
import type { SpeechStatus } from "../audio/types";
import { SpatialStage } from "../spatial/SpatialStage";
import { isDemoControlsEnabled } from "./shared";

interface HostDeviceAccess {
  device: DeviceInfo;
  token: string;
}

const REQUIRED_FACE_MATCH_FRAMES = 4;
const HOST_CAPTURE_LABELS: Partial<Record<SpeechStatus, string>> = {
  requesting_microphone: "请求麦克风",
  connecting_speech_ws: "连接中",
  recording: "录音中",
  stopping: "正在停止",
};

function formatFaceScore(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(3)
    : "--";
}

export function HostTabletConsole() {
  const bridge = useMemo(() => getNativeBridge(), []);
  return !bridge.isAvailable() && isDemoControlsEnabled()
    ? <HostBrowserPreview />
    : <NativeHostTabletConsole />;
}

function HostBrowserPreview() {
  const navigate = useNavigate();
  return (
    <AdminDashboard
      onSwitchToSeat={(seatId) => navigate(`/seat/${seatId}`)}
      hostSpeechControl={<HostSpeechControl />}
    />
  );
}

function NativeHostTabletConsole() {
  const bridge = useMemo(() => getNativeBridge(), []);
  const [deviceAccess, setDeviceAccess] = useState<HostDeviceAccess | null>(null);
  const [unlocked, setUnlocked] = useState(false);
  const [pendingUnlock, setPendingUnlock] = useState(false);
  const [identity, setIdentity] = useState<HostIdentityProfile>({
    defaultPersonId: null,
    registeredPersonIds: [],
  });
  const [denied, setDenied] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    let active = true;
    const unsubscribe = subscribeNativeEvents((event) => {
      if (event.type === "host_console_access") {
        const data = event.data as { granted?: boolean; pending?: boolean };
        if (active) {
          setUnlocked(data.granted === true);
          setPendingUnlock(data.pending === true);
        }
      } else if (event.type === "host_identity") {
        if (active) setIdentity(event.data as HostIdentityProfile);
      }
    });

    void (async () => {
      try {
        if (!bridge.isAvailable()) {
          throw new Error("主持人控制台仅允许从已绑定的 Seat 1 Android 平板进入");
        }
        const device = await bridge.getDeviceInfo();
        if (!device.configured || device.seatId !== 1) {
          throw new Error("当前设备不是已启用并绑定 Seat 1 的主持人平板");
        }
        const [token, access, hostIdentity] = await Promise.all([
          bridge.getDeviceCredential(),
          bridge.getHostConsoleAccess(),
          bridge.getDefaultHostIdentity(),
        ]);
        if (!active) return;
        setDeviceAccess({ device, token });
        setUnlocked(access.granted);
        setPendingUnlock(access.pending);
        setIdentity(hostIdentity);
      } catch (reason) {
        if (active) {
          setDenied(reason instanceof Error ? reason.message : "主持人设备验证失败");
        }
      } finally {
        if (active) setInitializing(false);
      }
    })();

    return () => {
      active = false;
      unsubscribe();
    };
  }, [bridge]);

  const requestUnlock = useCallback(async () => {
    setDenied(null);
    try {
      const result = await bridge.requestHostConsoleAccess();
      setUnlocked(result.granted);
      setPendingUnlock(result.pending);
    } catch (reason) {
      setDenied(reason instanceof Error ? reason.message : "无法打开 PIN 验证");
    }
  }, [bridge]);

  if (initializing) return <HostGate message="正在验证主持人设备…" busy />;
  if (!deviceAccess) return <HostGate message={denied ?? "主持人设备验证失败"} denied />;
  if (!unlocked) {
    return (
      <HostGate
        message={denied ?? "输入维护 PIN 进入主持人控制台"}
        busy={pendingUnlock}
        denied={denied != null}
        onUnlock={() => void requestUnlock()}
      />
    );
  }

  return (
    <div data-testid="host-tablet-console" className="relative min-h-screen">
      <AdminDashboard
        hostTabletAccess={{
          deviceId: deviceAccess.device.deviceId,
          token: deviceAccess.token,
          heartbeat: {
            seatId: 1,
            appVersion: deviceAccess.device.appVersion ?? "unknown",
            cameraStatus: deviceAccess.device.cameraReady === true
              ? "READY"
              : deviceAccess.device.cameraReady === false ? "ERROR" : "UNKNOWN",
            faceModelStatus: deviceAccess.device.faceModelReady === true
              ? "READY"
              : deviceAccess.device.faceModelReady === false ? "ERROR" : "UNKNOWN",
            registeredTemplatesCount: identity.registeredPersonIds.length,
            microphoneStatus: bridge.supportsMicrophoneCapture()
              && deviceAccess.device.microphoneReady !== false ? "READY" : "ERROR",
            diagnosticStatus: deviceAccess.device.nativeLastError ? "ERROR" : "READY",
            lastError: deviceAccess.device.nativeLastError?.slice(0, 300) ?? null,
          },
        }}
        hostSeatCheckIn={(
          <HostCheckInCard
            access={deviceAccess}
            identity={identity}
            onIdentityChange={setIdentity}
          />
        )}
        hostSpeechControl={<HostSpeechControl />}
      />
      <MaintenanceHoldButton bridge={bridge} />
    </div>
  );
}

function HostGate({
  message,
  busy = false,
  denied = false,
  onUnlock,
}: {
  message: string;
  busy?: boolean;
  denied?: boolean;
  onUnlock?: () => void;
}) {
  const phase = busy ? "busy" : denied ? "fault" : "idle";
  return (
    <main data-spatial-mode="identity" data-spatial-phase={phase} className="desk-page grid min-h-dvh place-items-center p-4 text-techText sm:p-8">
      <div className="desk-panel grid w-full max-w-5xl overflow-hidden md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="relative min-h-48 md:min-h-[25rem]">
          <div className="absolute inset-0">
            <SpatialStage
              className="spatial-gate-stage h-full w-full"
              state={{ mode: "identity", phase, selectedSeat: 1 }}
            />
          </div>
        </div>
        <div className="spatial-gate-card grid content-center border-t border-techBorder p-6 text-center sm:p-9 md:border-l md:border-t-0 md:text-left">
          <div className="desk-brand-mark mx-auto grid h-12 w-12 place-items-center md:mx-0">
            {busy ? <Loader2 className="animate-spin text-techCyan" /> : <LockKeyhole className="text-techCyan" />}
          </div>
          <h1 className="mt-5 text-2xl font-bold sm:text-3xl">主持人控制台</h1>
          <p className="mt-2 text-sm text-techMuted">{message}</p>
          {onUnlock && (
            <div className="mt-6">
              <button
                data-testid="unlock-host-console"
                disabled={busy}
                onClick={onUnlock}
                className="min-h-11 rounded-lg bg-techCyan px-5 py-2.5 text-sm font-semibold text-techBg disabled:opacity-50"
              >
                {busy ? "等待 PIN 验证…" : "输入维护 PIN"}
              </button>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function HostCheckInCard({
  access,
  identity,
  onIdentityChange,
}: {
  access: HostDeviceAccess;
  identity: HostIdentityProfile;
  onIdentityChange: (value: HostIdentityProfile) => void;
}) {
  const bridge = useMemo(() => getNativeBridge(), []);
  const {
    meeting,
    attendees,
    seats,
    loading,
    error,
    refresh,
  } = useSeatData(1);
  const [faceOpen, setFaceOpen] = useState(false);
  const [nativeStatus, setNativeStatus] = useState<NativeIdentityStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const latestIdentityEvent = useRef<SmartDeskNativeEvent | null>(null);
  const submittedEventId = useRef<string | null>(null);

  const assigned = attendees.find((person) => person.assigned_seat_id === 1)
    ?? attendees.find((person) => person.seat_id === 1)
    ?? null;
  const seat = seats.find((item) => item.seatId === 1);
  const checkedIn = seat?.isCheckedIn === true || Boolean(assigned?.checked_in && assigned.seat_id === 1);
  const defaultMatches = Boolean(
    assigned?.person_id && identity.defaultPersonId === assigned.person_id,
  );
  const hasDefaultTemplate = Boolean(
    identity.defaultPersonId
      && identity.registeredPersonIds.includes(identity.defaultPersonId),
  );
  const identityMode = access.device.identityMode === "debug" ? "debug" : "formal";

  useEffect(() => subscribeNativeEvents((event) => {
    if (event.type === "identity_status") {
      latestIdentityEvent.current = event;
      setNativeStatus(event.data as NativeIdentityStatus);
    } else if (event.type === "host_identity") {
      onIdentityChange(event.data as HostIdentityProfile);
    }
  }), [onIdentityChange]);

  const stopVerification = useCallback(async () => {
    await bridge.stopFaceVerification().catch(() => undefined);
    setFaceOpen(false);
    setNativeStatus(null);
    latestIdentityEvent.current = null;
  }, [bridge]);

  useEffect(() => {
    const event = latestIdentityEvent.current;
    if (
      !faceOpen
      || busy
      || !event
      || event.type !== "identity_status"
      || event.eventId === submittedEventId.current
      || nativeStatus?.status !== "VERIFIED"
      || !nativeStatus.personId
      || nativeStatus.similarity == null
    ) return;
    submittedEventId.current = event.eventId;
    setBusy(true);
    setActionError(null);
    void identityCheckinSeat(1, {
      eventId: event.eventId,
      eventTimestamp: event.timestamp,
      personCode: nativeStatus.personId,
      deviceId: access.device.deviceId,
      deviceSeatId: 1,
      status: nativeStatus.status,
      similarity: nativeStatus.similarity,
      thresholdStatus: nativeStatus.thresholdStatus ?? "CALIBRATION_PENDING",
      verificationLevel: nativeStatus.verificationLevel ?? "NONE",
      modelVersion: nativeStatus.modelVersion ?? null,
    }, access.token)
      .then(async () => {
        await stopVerification();
        refresh();
      })
      .catch((reason) => {
        setActionError(reason instanceof Error ? reason.message : "主持人签到失败");
        submittedEventId.current = null;
      })
      .finally(() => setBusy(false));
  }, [access, busy, faceOpen, nativeStatus, refresh, stopVerification]);

  const beginCheckIn = async () => {
    setActionError(null);
    if (!assigned?.person_id) return;
    setBusy(true);
    try {
      if (identityMode === "debug") {
        await debugAdmitSeat(1, {
          deviceId: access.device.deviceId,
          deviceSeatId: 1,
        }, access.token);
        refresh();
        return;
      }
      setFaceOpen(true);
      submittedEventId.current = null;
      await bridge.startFaceVerification(assigned.person_id);
    } catch (reason) {
      setFaceOpen(false);
      setActionError(reason instanceof Error ? reason.message : "无法启动主持人人脸验证");
    } finally {
      setBusy(false);
    }
  };

  let statusText = "等待会议创建或开始";
  let canCheckIn = false;
  if (loading) statusText = "正在读取 Seat 1 状态…";
  else if (error) statusText = `状态读取失败：${error}`;
  else if (!meeting) statusText = "当前没有进行中的会议";
  else if (!assigned) statusText = "本场尚未分配主持人，请先在模板管理页分配 Seat 1";
  else if (checkedIn) statusText = `${assigned.name} 已完成 Seat 1 签到`;
  else if (!hasDefaultTemplate) statusText = "请先注册并选择默认主持人本机模板";
  else if (!defaultMatches) statusText = "本场 Seat 1 人员与默认主持人身份不一致";
  else {
    statusText = identityMode === "debug"
      ? `${assigned.name} 可使用 Debug 模式签到`
      : `${assigned.name} 尚未签到，请主动开始人脸验证`;
    canCheckIn = true;
  }

  const isFinalSimilarity = nativeStatus?.status === "VERIFIED"
    || nativeStatus?.status === "UNKNOWN"
    || nativeStatus?.status === "RETRY_REQUIRED";
  const stageSampleCount = nativeStatus?.stageSampleCount ?? 0;
  const stageRequiredSamples = nativeStatus?.stageRequiredSamples ?? 5;
  const agreeingFrames = nativeStatus?.matchStreak ?? 0;

  return (
    <>
      <section
        data-testid="host-seat-checkin-card"
        className="rounded-lg border border-techCyan/30 bg-techCard p-5 text-techText shadow-card-glow"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <UserCheck size={18} className="text-techCyan" />
            <strong className="text-sm">Seat 1 · 主持人签到</strong>
          </div>
          {identityMode === "debug" && (
            <span className="rounded bg-amber-400/20 px-2 py-1 text-[0.65rem] font-bold text-amber-300">DEBUG · 跳过人脸</span>
          )}
        </div>
        <p className="mt-2 text-xs leading-5 text-techMuted">{statusText}</p>
        {actionError && <p className="mt-2 text-xs text-techRose">{actionError}</p>}
        {!checkedIn && meeting && (
          <button
            data-testid="host-seat-checkin"
            disabled={!canCheckIn || busy}
            onClick={() => void beginCheckIn()}
            className="mt-3 w-full rounded-lg bg-techCyan px-4 py-2 text-sm font-semibold text-techBg disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "正在处理…" : identityMode === "debug" ? "Seat 1 Debug 签到" : "开始 Seat 1 人脸签到"}
          </button>
        )}
      </section>


      {faceOpen && (
        <div className="fixed inset-0 z-[80] grid place-items-center overflow-auto bg-slate-950/80 p-6 text-white backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-3xl border border-cyan-500/40 bg-slate-900/90 p-8 text-center">
            <ShieldCheck className="mx-auto text-cyan-400" size={48} />
            <h2 className="mt-4 text-xl font-bold">主持人人脸验证</h2>
            <p className="mt-3 text-sm text-slate-300" role="status">{nativeStatus?.message ?? "请保持正对摄像头并稍后"}</p>
            {actionError && <p className="mt-3 text-sm text-red-300">{actionError}</p>}
            <button onClick={() => void stopVerification()} className="mt-6 inline-flex items-center gap-2 rounded-lg border border-slate-600 px-4 py-2 text-sm">
              <X size={15} />取消验证
            </button>
            <details className="mt-4 text-left">
              <summary className="cursor-pointer text-sm text-slate-300">验证详情</summary>
              <p className="mt-2 font-mono text-xs text-cyan-300">{nativeStatus?.status ?? "STARTING"}</p>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-cyan-500/20 bg-slate-950/40 p-3">
                  <p className="text-xs text-slate-400">{isFinalSimilarity ? "最终聚合相似度" : "实时相似度"}</p>
                  <p data-testid="face-live-similarity" className="mt-1 font-mono text-xl font-semibold text-cyan-300">
                    {formatFaceScore(nativeStatus?.similarity)}
                  </p>
                </div>
                <div className="rounded-xl border border-cyan-500/20 bg-slate-950/40 p-3">
                  <p className="text-xs text-slate-400">当前阈值</p>
                  <p data-testid="face-threshold" className="mt-1 font-mono text-xl font-semibold text-cyan-300">
                    {formatFaceScore(nativeStatus?.threshold)}
                  </p>
                </div>
                <div className="rounded-xl border border-cyan-500/20 bg-slate-950/40 p-3">
                  <p className="text-xs text-slate-400">采样进度</p>
                  <p data-testid="face-sample-progress" className="mt-1 font-mono text-lg text-slate-100">
                    {stageSampleCount}/{stageRequiredSamples}
                  </p>
                </div>
                <div className="rounded-xl border border-cyan-500/20 bg-slate-950/40 p-3">
                  <p className="text-xs text-slate-400">达标帧数</p>
                  <p data-testid="face-qualified-frames" className="mt-1 font-mono text-lg text-slate-100">
                    {agreeingFrames}/{REQUIRED_FACE_MATCH_FRAMES}
                  </p>
                </div>
              </div>
              <p className="mt-3 text-xs leading-5 text-slate-400">
                最终通过需聚合相似度达到阈值，且至少 4 帧单帧相似度达到阈值。
              </p>
            </details>
          </div>
        </div>
      )}
    </>
  );
}

function HostSpeechControl() {
  const [captureStatus, setCaptureStatus] = useState<SpeechStatus>("idle");
  const {
    meeting,
    attendees,
    seats,
    speakerSeatId,
    connection,
    error,
    terminateUtterance,
  } = useSeatData(1);
  const assigned = attendees.find((person) => person.assigned_seat_id === 1)
    ?? attendees.find((person) => person.seat_id === 1)
    ?? null;
  const seat = seats.find((item) => item.seatId === 1);
  const checkedIn = seat?.isCheckedIn === true
    || Boolean(assigned?.checked_in && assigned.seat_id === 1);

  return (
    <details className="host-disclosure">
      <summary className="host-toolbar__link" aria-label="主持席麦克风 / Host Microphone">
        <Mic size={16} aria-hidden="true" />
        <span>发言</span>
        <span className="host-mic-indicator" role="status">{HOST_CAPTURE_LABELS[captureStatus]}</span>
      </summary>
      <div className="host-disclosure__panel">
        <SpeechControl
          meetingId={meeting?.id ?? null}
          seatId={1}
          isSpeaker={checkedIn && speakerSeatId === 1}
          isCheckedIn={checkedIn}
          writesAllowed={connection === "connected" && !error && meeting?.status === "active"}
          meetingStatus={meeting?.status === "active" ? "meeting_active" : "no_meeting"}
          onLocalTerminalUtterance={terminateUtterance}
          onSpeechStatusChange={setCaptureStatus}
        />
      </div>
    </details>
  );
}

function MaintenanceHoldButton({
  bridge,
}: {
  bridge: ReturnType<typeof getNativeBridge>;
}) {
  const cancel = () => void bridge.cancelMaintenanceHold().catch(() => undefined);
  return (
    <button
      data-testid="host-maintenance-hold"
      aria-label="长按进入人脸模板管理"
      title="长按 5 秒进入人脸模板管理"
      onPointerDown={() => void bridge.beginMaintenanceHold()}
      onPointerUp={cancel}
      onPointerCancel={cancel}
      onPointerLeave={cancel}
      className="fixed right-5 top-5 z-50 grid h-11 w-11 place-items-center rounded-full border border-techBorder bg-techCard/95 text-techMuted shadow-lg backdrop-blur hover:text-techCyan"
    >
      <Settings size={18} />
    </button>
  );
}
