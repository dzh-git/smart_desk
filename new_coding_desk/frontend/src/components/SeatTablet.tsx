import {
  useCallback,
  useState,
  useMemo,
  useEffect,
  useRef,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  Cpu,
  ArrowLeft,
  Wifi,
  WifiOff,
  Loader2,
  AlertCircle,
  RefreshCw,
  UserCheck,
  Mic,
  MicOff,
  Coffee,
  Droplets,
  Leaf,
  MoreHorizontal,
  XCircle,
  Clock,
  Vote,
  CheckCircle2,
  Square,
  List,
  Monitor,
} from "lucide-react";
import { useSeatData } from "../hooks/useSeatData";
import { useClock, formatTime, formatDuration } from "./shared";
import { isDemoControlsEnabled } from "./shared";
import { useSpeechStream } from "../hooks/useSpeechStream";
import { isMicrophoneCaptureSupported } from "../audio/microphone";
import { TranscriptPanel } from "./TranscriptPanel";
import {
  identityCheckinSeat,
  tabletVacateSeat,
  devVacateSeat,
  submitVote,
  createServiceCall,
  cancelServiceCall,
  fetchSpeechStatus,
  reportTabletHeartbeat,
  debugAdmitSeat,
} from "../api/resources";
import { ApiError, NetworkError } from "../api/client";
import type { ServiceType, SpeechModelStatus, VoteStatistics } from "../api/types";
import {
  deriveSeatMeetingStatus,
  canVacateSeat,
  canSubmitVote,
  canSelectVoteOption,
  canCallService,
  canCancelService,
  canStartSpeech,
} from "../utils/uiState";
import { deriveAgendaState } from "../utils/agendaState";
import {
  getNativeBridge,
  type DeviceInfo,
} from "../native/NativeBridge";
import {
  subscribeNativeEvents,
  type NativeIdentityStatus,
  type SmartDeskNativeEvent,
} from "../native/nativeEvents";

// Shared dark-theme components
import {
  PanelCard,
  StatusBadge,
  ActionButton,
  DualLabel,
  SectionHeader,
} from "./shared";

// ── Helpers ──────────────────────────────────────────────────────────────────

function cx(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(" ");
}

const IDENTITY_SUBMIT_RETRY_MS = [1_000, 2_000, 5_000] as const;
const ACTIVE_IDENTITY_STATUSES = new Set([
  "VERIFYING",
  "WAITING_FOR_FACE",
  "MULTIPLE_FACES",
]);
function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

// ── Props ────────────────────────────────────────────────────────────────────

interface SeatTabletProps {
  seatId: number;
  onSwitchToAdmin?: () => void;
}

// ── Main Component ───────────────────────────────────────────────────────────

export function SeatTablet({ seatId, onSwitchToAdmin }: SeatTabletProps) {
  const navigate = useNavigate();
  const {
    loading,
    error,
    meeting,
    seats,
    speakerSeatId,
    attendees,
    agenda,
    activeVote,
    voteStats,
    voteResults,
    voteStatsError,
    currentServiceCall,
    translations,
    liveFinal,
    interimMap,
    lyricMap,
    pendingFinalMap,
    connection,
    noMeeting,
    refresh,
    terminateUtterance,
  } = useSeatData(seatId);

  // Local UI state
  const [selectedVoteOption, setSelectedVoteOption] = useState<string | null>(
    null,
  );
  const [submittingVote, setSubmittingVote] = useState(false);
  const [creatingService, setCreatingService] = useState(false);
  const [cancellingService, setCancellingService] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const nativeBridge = useMemo(() => getNativeBridge(), []);
  const [nativeDeviceInfo, setNativeDeviceInfo] = useState<DeviceInfo | null>(
    null,
  );
  const [nativeIdentityStatus, setNativeIdentityStatus] =
    useState<NativeIdentityStatus | null>(null);
  const [identityCheckinSubmitting, setIdentityCheckinSubmitting] =
    useState(false);
  const [tabletVacateSubmitting, setTabletVacateSubmitting] =
    useState(false);
  const nativeDeviceCredential = useRef<string | null>(null);
  const [nativeCredentialReady, setNativeCredentialReady] = useState(false);
  const [nativeRuntimeError, setNativeRuntimeError] = useState<string | null>(
    null,
  );
  const nativeIdentityEvent = useRef<SmartDeskNativeEvent | null>(
    null,
  );
  const submittedIdentityKey = useRef<string | null>(null);
  const identitySubmitRun = useRef(0);
  const automaticFaceAttemptKey = useRef<string | null>(null);
  const [faceTemplateSyncRetry, setFaceTemplateSyncRetry] = useState(0);
  const automaticDebugAdmitKey = useRef<string | null>(null);
  const [debugAdmitRetry, setDebugAdmitRetry] = useState(0);

  useEffect(() => {
    let active = true;
    const unsubscribe = subscribeNativeEvents((event) => {
      if (event.type === "identity_status") {
        nativeIdentityEvent.current = event;
        setNativeIdentityStatus(event.data as NativeIdentityStatus);
        if ((event.data as NativeIdentityStatus).status === "ERROR") {
          setNativeRuntimeError(
            (event.data as NativeIdentityStatus).message ??
              "Native identity error",
          );
        }
      } else if (event.type === "error") {
        const data = event.data as { code?: string; message?: string };
        const nativeError =
          [data.code, data.message].filter(Boolean).join("：") ||
          "Android native operation failed";
        setNativeRuntimeError(nativeError);
        setActionError(
          nativeError,
        );
      }
    });

    if (nativeBridge.isAvailable()) {
      void nativeBridge
        .getDeviceInfo()
        .then((deviceInfo) => {
          if (active) {
            setNativeDeviceInfo(deviceInfo);
            setNativeRuntimeError(deviceInfo.nativeLastError ?? null);
          }
        })
        .catch((error: unknown) => {
          if (active) {
            setActionError(
              error instanceof Error
                ? error.message
                : "Unable to read Android device configuration",
            );
          }
        });
      void nativeBridge
        .getDeviceCredential()
        .then((deviceToken) => {
          if (active) {
            nativeDeviceCredential.current = deviceToken;
            setNativeCredentialReady(true);
          }
        })
        .catch((error: unknown) => {
          if (active) {
            setActionError(
              error instanceof Error
                ? error.message
                : "Unable to read Android device credential",
            );
          }
        });
    }

    return () => {
      active = false;
      unsubscribe();
      identitySubmitRun.current += 1;
      if (nativeBridge.isAvailable()) {
        void nativeBridge.stopFaceVerification().catch(() => undefined);
      }
    };
  }, [nativeBridge]);

  // Derived state
  const mySeat = seats.find((s) => s.seatId === seatId) ?? null;
  const isCheckedIn = mySeat?.isCheckedIn ?? false;
  const assignedAttendee =
    attendees.find((attendee) => attendee.assigned_seat_id === seatId) ?? null;
  const meetingAccessGranted =
    isCheckedIn &&
    assignedAttendee != null &&
    mySeat?.attendeeId === assignedAttendee.id;
  const isSpeaker = speakerSeatId === seatId;
  const wsConnected = connection === "connected";
  const identityMode = nativeDeviceInfo?.identityMode === "debug"
    ? "debug"
    : "formal";

  useEffect(() => {
    const deviceInfo = nativeDeviceInfo;
    const deviceToken = nativeDeviceCredential.current;
    if (
      !nativeBridge.isAvailable() ||
      !nativeCredentialReady ||
      !deviceInfo ||
      !deviceToken ||
      deviceInfo.seatId !== seatId
    ) {
      return;
    }

    let active = true;
    const heartbeat = async () => {
      const [identityResult, facesResult] = await Promise.allSettled([
        nativeBridge.getNativeStatus(),
        nativeBridge.getRegisteredFaces(),
      ]);
      if (!active) return;

      const identityError =
        identityResult.status === "rejected"
          ? identityResult.reason instanceof Error
            ? identityResult.reason.message
            : String(identityResult.reason)
          : identityResult.value.status === "ERROR"
            ? identityResult.value.message ?? "Native identity error"
            : null;
      const facesError =
        facesResult.status === "rejected"
          ? facesResult.reason instanceof Error
            ? facesResult.reason.message
            : String(facesResult.reason)
          : null;
      const lastError = (
        nativeRuntimeError ??
        deviceInfo.nativeLastError ??
        identityError ??
        facesError
      )?.slice(0, 300) ?? null;
      const statusFromCapability = (
        ready: boolean | undefined,
      ): "READY" | "ERROR" | "UNKNOWN" =>
        ready === true ? "READY" : ready === false ? "ERROR" : "UNKNOWN";

      try {
        await reportTabletHeartbeat(
          deviceInfo.deviceId,
          {
            seatId,
            appVersion: deviceInfo.appVersion ?? "unknown",
            cameraStatus: statusFromCapability(deviceInfo.cameraReady),
            faceModelStatus:
              identityResult.status === "fulfilled"
                ? statusFromCapability(deviceInfo.faceModelReady)
                : "ERROR",
            registeredTemplatesCount:
              facesResult.status === "fulfilled"
                ? facesResult.value.count
                : 0,
            microphoneStatus:
              isMicrophoneCaptureSupported() && deviceInfo.microphoneReady !== false
                ? statusFromCapability(deviceInfo.microphoneReady ?? true)
                : "ERROR",
            meetingWebsocketStatus: connection.toUpperCase() as
              | "CONNECTED"
              | "CONNECTING"
              | "DISCONNECTED",
            diagnosticStatus: lastError ? "ERROR" : "READY",
            lastError,
          },
          deviceToken,
        );
      } catch {
        // A missed heartbeat is represented by last_seen_at becoming stale.
        // Do not surface a recurring network error over the meeting UI.
      }
    };

    void heartbeat();
    const timer = window.setInterval(heartbeat, 15_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [
    connection,
    nativeBridge,
    nativeCredentialReady,
    nativeDeviceInfo,
    nativeRuntimeError,
    seatId,
  ]);
  const latestClosedVote =
    voteResults.find((vote) => vote.status === "closed") ?? null;
  const displayVoteStats = voteStats ?? latestClosedVote;
  const displayVote =
    activeVote ??
    (displayVoteStats
      ? {
          id: displayVoteStats.vote_id,
          title: displayVoteStats.title,
          options: displayVoteStats.results.map((item) => item.option),
          status: displayVoteStats.status,
          is_anonymous: displayVoteStats.is_anonymous,
        }
      : null);

  const agendaState = deriveAgendaState(agenda);
  // Elapsed time
  const now = useClock();
  const elapsedMs =
    meeting?.started_at != null
      ? now.getTime() - new Date(meeting.started_at).getTime()
      : 0;

  // Current attendee name for this seat (memoized)
  const myAttendeeName = mySeat?.attendeeName ?? null;
  const myAttendeeTitle = mySeat?.attendeeTitle ?? null;

  // Build seat → name map for TranscriptPanel
  const seatNameMap: Record<number, string> = {};
  for (const a of attendees) {
    if (a.seat_id != null) {
      seatNameMap[a.seat_id] = a.name;
    }
  }

  // Get the current vote submission status for this seat's attendee.
  // Uses seat-bound attendeeId (stable) instead of name lookup to avoid
  // selecting the wrong attendee when two share the same name.
  const myAttendeeId = mySeat?.attendeeId ?? null;
  const voteSubmission = useMemo(() => {
    if (!displayVoteStats || !myAttendeeId) return null;

    for (const result of displayVoteStats.results) {
      if (result.attendee_ids?.includes(myAttendeeId)) {
        return { option: result.option, attendeeId: myAttendeeId };
      }
    }
    // If anonymous, we can't check, but let's still allow submission
    return { option: null, attendeeId: myAttendeeId };
  }, [displayVoteStats, myAttendeeId]);

  // ── Actions ─────────────────────────────────────────────────────────────

  const handleFaceVerification = useCallback(async () => {
    setActionError(null);
    const expectedPersonId = assignedAttendee?.person_id;
    if (!expectedPersonId) {
      setActionError("当前席位尚未分配可验证人员");
      return;
    }
    if (
      nativeDeviceInfo?.seatId != null &&
      nativeDeviceInfo.seatId !== seatId
    ) {
      setActionError(
        `设备绑定席位 ${nativeDeviceInfo.seatId} 与当前页面席位 ${seatId} 不一致`,
      );
      return;
    }

    setNativeIdentityStatus({
      status: "VERIFYING",
      message: "正在启动 Android 本地人脸验证",
    });
    nativeIdentityEvent.current = null;
    try {
      await nativeBridge.startFaceVerification(expectedPersonId);
    } catch (error: unknown) {
      setActionError(
        error instanceof Error
          ? error.message
          : "Unable to start native face verification",
      );
      setNativeIdentityStatus({
        status: "ERROR",
        message:
          error instanceof Error
            ? error.message
            : "Unable to start native face verification",
      });
    }
  }, [assignedAttendee?.person_id, nativeBridge, nativeDeviceInfo, seatId]);

  const handleStopFaceVerification = useCallback(async () => {
    setActionError(null);
    try {
      await nativeBridge.stopFaceVerification();
    } catch (error: unknown) {
      setActionError(
        error instanceof Error
          ? error.message
          : "Unable to stop native face verification",
      );
    }
  }, [nativeBridge]);

  const submitIdentityCheckin = useCallback(
    async (identity: NativeIdentityStatus): Promise<boolean> => {
      if (
        !nativeDeviceInfo ||
        !identity.personId ||
        identity.similarity == null
      ) {
        setActionError(
          "身份签到缺少设备编号、稳定 personId 或相似度",
        );
        return false;
      }
      const sourceEvent = nativeIdentityEvent.current;
      if (!sourceEvent || sourceEvent.type !== "identity_status") {
        setActionError("身份签到缺少原生事件编号");
        return false;
      }
      const deviceToken = nativeDeviceCredential.current;
      if (!deviceToken) {
        setActionError("身份签到缺少设备认证密钥");
        return false;
      }
      if (nativeDeviceInfo.seatId !== seatId) {
        setActionError(
          `设备绑定席位 ${nativeDeviceInfo.seatId ?? "未配置"} 与当前页面席位 ${seatId} 不一致`,
        );
        return false;
      }

      const runId = ++identitySubmitRun.current;
      setIdentityCheckinSubmitting(true);
      setActionError(null);
      try {
        for (let attempt = 0; attempt <= IDENTITY_SUBMIT_RETRY_MS.length; attempt += 1) {
          try {
            await identityCheckinSeat(
              seatId,
              {
                eventId: sourceEvent.eventId,
                eventTimestamp: sourceEvent.timestamp,
                personCode: identity.personId,
                deviceId: nativeDeviceInfo.deviceId,
                deviceSeatId: nativeDeviceInfo.seatId,
                status: identity.status,
                similarity: identity.similarity,
                thresholdStatus:
                  identity.thresholdStatus ?? "CALIBRATION_PENDING",
                verificationLevel:
                  identity.verificationLevel ?? "NONE",
                modelVersion: identity.modelVersion ?? null,
              },
              deviceToken,
            );
            if (runId === identitySubmitRun.current) {
              refresh();
            }
            return true;
          } catch (error: unknown) {
            const retryable =
              error instanceof NetworkError ||
              (error instanceof ApiError && error.statusCode >= 500);
            if (
              !retryable ||
              attempt === IDENTITY_SUBMIT_RETRY_MS.length
            ) {
              throw error;
            }
            await delay(IDENTITY_SUBMIT_RETRY_MS[attempt]);
            if (runId !== identitySubmitRun.current) {
              return false;
            }
          }
        }
        return false;
      } catch (error: unknown) {
        if (
          error instanceof ApiError &&
          error.errorCode === "FACE_TEMPLATE_SYNC_INCOMPLETE"
        ) {
          automaticFaceAttemptKey.current = null;
          submittedIdentityKey.current = null;
          nativeIdentityEvent.current = null;
          setNativeIdentityStatus(null);
          await nativeBridge.stopFaceVerification().catch(() => undefined);
          setFaceTemplateSyncRetry((value) => value + 1);
        }
        setActionError(
          error instanceof Error
            ? error.message
            : "Identity check-in failed",
        );
        return false;
      } finally {
        if (runId === identitySubmitRun.current) {
          setIdentityCheckinSubmitting(false);
        }
      }
    },
    [nativeBridge, nativeDeviceInfo, refresh, seatId],
  );

  useEffect(() => {
    if (nativeIdentityStatus?.status !== "VERIFIED") {
      if (nativeIdentityStatus?.status === "VERIFYING") {
        submittedIdentityKey.current = null;
      }
      return;
    }
    const identityKey = nativeIdentityEvent.current?.eventId;
    if (!identityKey) return;
    if (submittedIdentityKey.current === identityKey) return;
    submittedIdentityKey.current = identityKey;
    void submitIdentityCheckin(nativeIdentityStatus).then((success) => {
      if (!success && submittedIdentityKey.current === identityKey) {
        submittedIdentityKey.current = null;
      }
    });
  }, [nativeIdentityStatus, submitIdentityCheckin]);

  async function handleTabletVacate() {
    const deviceInfo = nativeDeviceInfo;
    const deviceToken = nativeDeviceCredential.current;
    if (!deviceInfo || !deviceToken || deviceInfo.seatId !== seatId) {
      setActionError("当前平板缺少有效的席位绑定或设备认证密钥");
      return;
    }
    if (
      !window.confirm(
        "确认离开当前席位？离席后将解除签到并重新等待人脸识别。",
      )
    ) {
      return;
    }
    setTabletVacateSubmitting(true);
    setActionError(null);
    try {
      await tabletVacateSeat(
        seatId,
        {
          deviceId: deviceInfo.deviceId,
          deviceSeatId: deviceInfo.seatId,
        },
        deviceToken,
      );
      submittedIdentityKey.current = null;
      setNativeIdentityStatus(null);
      refresh();
    } catch (error: unknown) {
      setActionError(
        error instanceof Error ? error.message : "Tablet vacate failed",
      );
    } finally {
      setTabletVacateSubmitting(false);
    }
  }

  async function handleVacate() {
    setActionError(null);
    try {
      await devVacateSeat(seatId);
      refresh();
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Vacate failed",
      );
    }
  }

  async function handleVoteSubmit() {
    if (!activeVote || activeVote.status !== "open") return;
    if (!selectedVoteOption || !voteSubmission?.attendeeId) return;
    setSubmittingVote(true);
    setActionError(null);
    try {
      await submitVote(
        activeVote.id,
        voteSubmission.attendeeId,
        selectedVoteOption,
      );
      setSelectedVoteOption(null);
      refresh();
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Vote submission failed",
      );
    } finally {
      setSubmittingVote(false);
    }
  }

  async function handleServiceCall(type: ServiceType) {
    if (!meeting?.id) return;
    setCreatingService(true);
    setActionError(null);
    try {
      await createServiceCall(meeting.id, seatId, type);
      refresh();
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Service call failed",
      );
    } finally {
      setCreatingService(false);
    }
  }

  async function handleCancelService() {
    if (!currentServiceCall) return;
    setCancellingService(true);
    setActionError(null);
    try {
      await cancelServiceCall(currentServiceCall.id);
      refresh();
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Cancel failed",
      );
    } finally {
      setCancellingService(false);
    }
  }

  // ── Whether writes are allowed (Task 4) ─────────────────────────────────

  const meetingStatus = deriveSeatMeetingStatus(meeting);
  const writesAllowed =
    wsConnected && !error && !!meeting && meeting?.status === "active";
  const tabletVacateAvailable =
    nativeBridge.isAvailable() &&
    nativeCredentialReady &&
    nativeDeviceInfo?.seatId === seatId;

  useEffect(() => {
    const deviceToken = nativeDeviceCredential.current;
    const eligible =
      identityMode === "debug" &&
      !meetingAccessGranted &&
      assignedAttendee != null &&
      writesAllowed &&
      nativeCredentialReady &&
      deviceToken != null &&
      nativeDeviceInfo?.seatId === seatId;

    if (!eligible || !nativeDeviceInfo || !deviceToken) {
      automaticDebugAdmitKey.current = null;
      return;
    }

    const admitKey = `${meeting?.id}:${seatId}:${assignedAttendee.id}`;
    if (automaticDebugAdmitKey.current === admitKey) return;
    automaticDebugAdmitKey.current = admitKey;
    setActionError(null);
    setNativeRuntimeError("DEBUG 模式：正在跳过人脸验证并完成签到…");
    void handleStopFaceVerification().catch(() => undefined);

    void debugAdmitSeat(
      seatId,
      {
        deviceId: nativeDeviceInfo.deviceId,
        deviceSeatId: seatId,
      },
      deviceToken,
    )
      .then(() => {
        setNativeRuntimeError(null);
        refresh();
      })
      .catch((error: unknown) => {
        const message = error instanceof Error
          ? error.message
          : "Debug 自动放行失败";
        setNativeRuntimeError(message);
        setActionError(message);
        window.setTimeout(() => {
          if (automaticDebugAdmitKey.current === admitKey) {
            automaticDebugAdmitKey.current = null;
            setDebugAdmitRetry((value) => value + 1);
          }
        }, 5_000);
      });
  }, [
    assignedAttendee,
    debugAdmitRetry,
    handleStopFaceVerification,
    identityMode,
    meeting?.id,
    meetingAccessGranted,
    nativeCredentialReady,
    nativeDeviceInfo,
    refresh,
    seatId,
    writesAllowed,
  ]);

  useEffect(() => {
    const eligible =
      identityMode === "formal" &&
      !meetingAccessGranted &&
      assignedAttendee?.person_id != null &&
      writesAllowed &&
      nativeBridge.isAvailable() &&
      nativeCredentialReady &&
      nativeDeviceInfo?.seatId === seatId;

    if (!eligible) {
      automaticFaceAttemptKey.current = null;
      if (ACTIVE_IDENTITY_STATUSES.has(nativeIdentityStatus?.status ?? "")) {
        void handleStopFaceVerification();
      }
      return;
    }

    const attemptKey = `${meeting?.id}:${seatId}:${assignedAttendee.id}`;
    if (automaticFaceAttemptKey.current === attemptKey) {
      return;
    }
    const status = nativeIdentityStatus?.status;
    if (status && ACTIVE_IDENTITY_STATUSES.has(status)) {
      return;
    }
    if (status === "VERIFIED") {
      return;
    }

    automaticFaceAttemptKey.current = attemptKey;
    let cancelled = false;
    void (async () => {
      try {
        if (seatId >= 2 && seatId <= 9 && meeting?.id != null) {
          setNativeRuntimeError("正在同步本次会议人脸模板…");
          await nativeBridge.syncFaceTemplates(meeting.id);
          if (cancelled) return;
          setNativeRuntimeError(null);
        }
        await handleFaceVerification();
      } catch (error: unknown) {
        if (cancelled) return;
        const syncError = error instanceof Error
          ? error.message
          : "会议人脸模板同步失败";
        setNativeRuntimeError(syncError);
        setActionError(syncError);
        window.setTimeout(() => {
          if (automaticFaceAttemptKey.current === attemptKey) {
            automaticFaceAttemptKey.current = null;
            setFaceTemplateSyncRetry((value) => value + 1);
          }
        }, 5_000);
      }
    })();
    return () => { cancelled = true; };
  }, [
    assignedAttendee,
    handleFaceVerification,
    handleStopFaceVerification,
    meeting?.id,
    meetingAccessGranted,
    nativeBridge,
    nativeCredentialReady,
    nativeDeviceInfo,
    nativeIdentityStatus?.status,
    seatId,
    writesAllowed,
    faceTemplateSyncRetry,
    identityMode,
  ]);

  const retryFaceVerification = useCallback(async () => {
    automaticFaceAttemptKey.current = null;
    submittedIdentityKey.current = null;
    nativeIdentityEvent.current = null;
    setNativeIdentityStatus(null);
    setActionError(null);
    await handleStopFaceVerification();
    if (seatId >= 2 && seatId <= 9 && meeting?.id != null) {
      setNativeRuntimeError("正在同步本次会议人脸模板…");
      await nativeBridge.syncFaceTemplates(meeting.id);
      setNativeRuntimeError(null);
    }
    await handleFaceVerification();
    automaticFaceAttemptKey.current = `${meeting?.id}:${seatId}:${assignedAttendee?.id}`;
  }, [
    assignedAttendee?.id,
    handleFaceVerification,
    handleStopFaceVerification,
    meeting?.id,
    nativeBridge,
    seatId,
  ]);

  const maintenanceAccessAvailable =
    nativeDeviceInfo?.maintenanceAccessAvailable === true;
  const beginMaintenanceHold = useCallback(() => {
    void nativeBridge.beginMaintenanceHold().catch((error: unknown) => {
      setActionError(
        error instanceof Error
          ? error.message
          : "Unable to open Android maintenance access",
      );
    });
  }, [nativeBridge]);
  const cancelMaintenanceHold = useCallback(() => {
    void nativeBridge.cancelMaintenanceHold().catch(() => undefined);
  }, [nativeBridge]);

  // ── Loading State ──────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen bg-techBg flex flex-col">
        <SeatHeader
          seatId={seatId}
          connection={connection}
          onBack={onSwitchToAdmin}
          onMaintenanceHoldStart={
            maintenanceAccessAvailable ? beginMaintenanceHold : undefined
          }
          onMaintenanceHoldEnd={
            maintenanceAccessAvailable ? cancelMaintenanceHold : undefined
          }
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4">
            <Loader2
              size={32}
              className="animate-spin text-techCyan mx-auto"
            />
            <p className="text-sm font-medium text-techMuted">
              正在加载席位数据 / Loading seat data...
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Error State ────────────────────────────────────────────────────────

  if (error && !meeting) {
    return (
      <div className="min-h-screen bg-techBg flex flex-col">
        <SeatHeader
          seatId={seatId}
          connection={connection}
          onBack={onSwitchToAdmin}
          onMaintenanceHoldStart={
            maintenanceAccessAvailable ? beginMaintenanceHold : undefined
          }
          onMaintenanceHoldEnd={
            maintenanceAccessAvailable ? cancelMaintenanceHold : undefined
          }
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4 max-w-md">
            <div className="w-14 h-14 rounded-full bg-techCyan/10 border-2 border-techCyan/30 flex items-center justify-center mx-auto">
              <Loader2 className="animate-spin text-techCyan" size={24} />
            </div>
            <p className="text-sm font-semibold text-techText">
              正在重新连接会议系统 / Reconnecting
            </p>
            <p className="text-xs text-techMuted">{error}</p>
            <ActionButton
              variant="primary"
              size="md"
              icon={<RefreshCw size={14} />}
              onClick={refresh}
            >
              <span>重试 / </span>
              <span>Retry</span>
            </ActionButton>
          </div>
        </div>
      </div>
    );
  }

  // ── No Meeting State ───────────────────────────────────────────────────

  if (noMeeting) {
    return (
      <div className="min-h-screen bg-techBg flex flex-col">
        <SeatHeader
          seatId={seatId}
          connection={connection}
          onBack={onSwitchToAdmin}
          onMaintenanceHoldStart={
            maintenanceAccessAvailable ? beginMaintenanceHold : undefined
          }
          onMaintenanceHoldEnd={
            maintenanceAccessAvailable ? cancelMaintenanceHold : undefined
          }
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4 max-w-md">
            <div className="w-16 h-16 rounded-full bg-techCardSoft border-2 border-techBorder flex items-center justify-center mx-auto">
              <Cpu className="text-techCyan" size={28} />
            </div>
            <p className="text-base font-bold text-techText">
              等待会议开始 / Waiting for Meeting
            </p>
            <p className="text-xs text-techMuted">
              会议开始后将自动启用此席位页面。 / The seat interface will activate once a meeting starts.
            </p>
            <ActionButton
              variant="secondary"
              size="md"
              icon={<RefreshCw size={14} />}
              onClick={refresh}
            >
              刷新 / Refresh
            </ActionButton>
          </div>
        </div>
      </div>
    );
  }

  if (!meetingAccessGranted) {
    const hasAssignment = assignedAttendee != null;
    const canRecognize = assignedAttendee?.person_id != null;
    const verificationActive = ACTIVE_IDENTITY_STATUSES.has(
      nativeIdentityStatus?.status ?? "",
    );
    return (
      <div
        data-testid="seat-page-scroll"
        className="h-screen overflow-y-auto bg-techBg bg-tech-radial flex flex-col"
      >
        <SeatHeader
          seatId={seatId}
          connection={connection}
          onBack={onSwitchToAdmin}
          meetingTitle={meeting?.title ?? undefined}
          elapsedMs={elapsedMs}
          onMaintenanceHoldStart={
            maintenanceAccessAvailable ? beginMaintenanceHold : undefined
          }
          onMaintenanceHoldEnd={
            maintenanceAccessAvailable ? cancelMaintenanceHold : undefined
          }
        />
        {error && (
          <div className="border-b border-techAmber/40 bg-techAmber/10 px-4 py-2 text-center text-xs font-semibold text-techAmber">
            连接暂时中断，正在自动重连；当前页面已保留，操作暂不可用。
          </div>
        )}
        <main
          data-testid="face-access-gate"
          className="flex-1 flex items-center justify-center p-6"
        >
          <div className="w-full max-w-xl rounded-2xl border border-techCyan/30 bg-techCard p-8 text-center shadow-cyan-glow">
            <div className="mx-auto mb-5 flex h-20 w-20 items-center justify-center rounded-full border-2 border-techCyan/40 bg-techCyan/10">
              <UserCheck size={36} className="text-techCyan" />
            </div>
            <h1 className="text-xl font-bold text-techText">
              人脸验证门禁 / Face Access
            </h1>
            {!hasAssignment ? (
              <p className="mt-4 text-sm text-techAmber">
                等待主持人分配席位人员 / Waiting for host seat assignment
              </p>
            ) : identityMode === "debug" ? (
              <div className="mt-5 space-y-2">
                <Loader2 size={28} className="mx-auto animate-spin text-techAmber" />
                <p className="text-base font-semibold text-techText">
                  {assignedAttendee.name}
                </p>
                <p className="text-sm text-techAmber">
                  Debug 模式正在自动完成签到，无需进行人脸验证。
                </p>
              </div>
            ) : !canRecognize ? (
              <div className="mt-4 space-y-2">
                <p className="text-base font-semibold text-techText">
                  {assignedAttendee.name}
                </p>
                <p className="text-sm text-techAmber">
                  默认人员尚未绑定人脸，只能由主持人人工放行。
                </p>
              </div>
            ) : (
              <div className="mt-5 space-y-4 text-left">
                <p className="text-center text-sm text-techMuted">
                  默认人员：{assignedAttendee.name}
                </p>
                <NativeIdentityPanel
                  automatic
                  status={nativeIdentityStatus}
                  onFaceVerification={handleFaceVerification}
                  onStopFaceVerification={handleStopFaceVerification}
                />
                {!verificationActive && (
                  <div className="flex justify-center">
                    <ActionButton
                      variant="primary"
                      size="md"
                      icon={<RefreshCw size={14} />}
                      onClick={() => void retryFaceVerification()}
                      disabled={identityCheckinSubmitting}
                    >
                      重新识别 / Retry Recognition
                    </ActionButton>
                  </div>
                )}
              </div>
            )}
            {actionError && (
              <p className="mt-5 rounded-lg border border-techRose/30 bg-techRose/10 px-4 py-3 text-sm text-techRose">
                {identityMode === "debug" ? "自动放行失败" : "验证失败"}：{actionError}
              </p>
            )}
            {!wsConnected && (
              <p className="mt-4 text-xs text-techAmber">
                后端连接已断开，恢复连接前不会解锁会议页面。
              </p>
            )}
            {identityMode === "debug" && (
              <div className="mt-5 rounded-lg border border-techAmber/50 bg-techAmber/10 px-4 py-3 text-sm font-semibold text-techAmber">
                DEBUG · 正在跳过人脸验证并自动签到
              </div>
            )}
          </div>
        </main>
      </div>
    );
  }

  // ── Active Meeting ─────────────────────────────────────────────────────

  return (
    <div
      data-testid="seat-page-scroll"
      className="h-screen overflow-y-auto bg-techBg bg-tech-radial relative"
    >
      <SeatHeader
        seatId={seatId}
        connection={connection}
        onBack={onSwitchToAdmin}
        meetingTitle={meeting?.title ?? undefined}
        elapsedMs={elapsedMs}
        onMaintenanceHoldStart={
          maintenanceAccessAvailable ? beginMaintenanceHold : undefined
        }
        onMaintenanceHoldEnd={
          maintenanceAccessAvailable ? cancelMaintenanceHold : undefined
        }
      />

      {error && (
        <div className="border-b border-techAmber/40 bg-techAmber/10 px-4 py-2 text-center text-xs font-semibold text-techAmber">
          连接暂时中断，正在自动重连；当前页面已保留，操作暂不可用。
        </div>
      )}

      <main className="p-4 space-y-4 max-w-[900px] mx-auto w-full">
        {identityMode === "debug" && (
          <div className="rounded-lg border border-techAmber/50 bg-techAmber/10 px-4 py-3 text-center text-sm font-bold text-techAmber">
            DEBUG · 已跳过人脸验证
          </div>
        )}
        {/* Action error */}
        {actionError && (
          <div className="bg-techRose/10 border border-techRose/30 rounded-lg px-4 py-3 flex items-center gap-2">
            <AlertCircle size={14} className="text-techRose flex-shrink-0" />
            <p className="text-xs text-techRose flex-1">操作失败 / Operation Failed：{actionError}</p>
            <button
              onClick={() => setActionError(null)}
              className="text-techRose/60 hover:text-techRose transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
            >
              <XCircle size={14} />
            </button>
          </div>
        )}

        {/* Shared screen entry — navigates to the read-only /screen viewer */}
        <button
          data-testid="seat-screen-entry"
          onClick={() => navigate("/screen")}
          className="w-full bg-techAccent/10 border border-techAccent/30 rounded-lg px-4 py-3 flex items-center justify-center gap-2 text-techAccent hover:bg-techAccent/20 transition-colors min-h-[44px]"
        >
          <Monitor size={16} />
          <span className="text-sm font-medium">共享画面 / Screen Share</span>
        </button>

        {/* Seat Status Card */}
        <SeatStatusCard
          seatId={seatId}
          isSpeaker={isSpeaker}
          myAttendee={myAttendeeName ? { name: myAttendeeName, title: myAttendeeTitle } : null}
          demoControlsEnabled={isDemoControlsEnabled()}
          onVacate={handleVacate}
          writesAllowed={writesAllowed}
          meetingStatus={meetingStatus}
          tabletVacateAvailable={tabletVacateAvailable}
          onTabletVacate={handleTabletVacate}
          tabletVacateSubmitting={tabletVacateSubmitting}
        />

        {/* Current Topic Card (read-only) */}
        <CurrentTopicCard agendaState={agendaState} />

        {/* Voting Section: open votes are writable; closed votes remain visible as final results. */}
        {isCheckedIn && displayVote && displayVoteStats && (
          <SeatVoteSection
            vote={displayVote}
            voteStats={displayVoteStats}
            voteStatsError={voteStatsError}
            currentVote={voteSubmission?.option ?? null}
            selectedOption={selectedVoteOption}
            onSelectOption={setSelectedVoteOption}
            onSubmit={handleVoteSubmit}
            submitting={submittingVote}
            writesAllowed={writesAllowed}
            meetingStatus={meetingStatus}
          />
        )}

        {/* Service Calls Section — only for checked-in seats */}
        {isCheckedIn && (
          <SeatServiceSection
            currentCall={currentServiceCall}
            onRequest={handleServiceCall}
            onCancel={handleCancelService}
            creating={creatingService}
            cancelling={cancellingService}
            writesAllowed={writesAllowed}
            meetingStatus={meetingStatus}
          />
        )}

        {/* Speech Control */}
        <SpeechControl
          meetingId={meeting?.id ?? null}
          seatId={seatId}
          isSpeaker={isSpeaker}
          isCheckedIn={isCheckedIn}
          writesAllowed={writesAllowed}
          meetingStatus={meetingStatus}
          onLocalTerminalUtterance={terminateUtterance}
        />

        {/* Bilingual Transcript */}
        <TranscriptPanel
          entries={translations}
          liveFinal={liveFinal}
          interims={Object.values(interimMap)}
          lyrics={Object.values(lyricMap).flat()}
          pendingFinals={Object.values(pendingFinalMap)}
          seatNameMap={seatNameMap}
          liveEnabled={meetingStatus === "meeting_active"}
          liveReconnecting={connection !== "connected"}
        />
      </main>

      {/* Disconnected overlay */}
      {connection === "disconnected" && (
        <div className="fixed inset-0 bg-techBg/80 backdrop-blur-sm flex flex-col items-center justify-center z-50">
          <div className="w-14 h-14 rounded-full bg-techRose/10 border-2 border-techRose/30 flex items-center justify-center mb-4">
            <WifiOff className="text-techRose" size={24} />
          </div>
          <p className="text-sm font-semibold text-techText mb-1">
            连接已断开 / Connection Lost
          </p>
          <p className="text-xs text-techMuted mb-4">
            正在尝试重新连接… / Attempting to reconnect...
          </p>
          <ActionButton
            variant="secondary"
            size="sm"
            icon={<RefreshCw size={12} />}
            onClick={refresh}
          >
            立即重试 / Retry Now
          </ActionButton>
        </div>
      )}
    </div>
  );
}

// ── Seat Header ──────────────────────────────────────────────────────────────

interface SeatHeaderProps {
  seatId: number;
  connection: "connecting" | "connected" | "disconnected";
  onBack?: () => void;
  meetingTitle?: string;
  elapsedMs?: number;
  onMaintenanceHoldStart?: () => void;
  onMaintenanceHoldEnd?: () => void;
}

function SeatHeader({
  seatId,
  connection,
  onBack,
  meetingTitle,
  elapsedMs,
  onMaintenanceHoldStart,
  onMaintenanceHoldEnd,
}: SeatHeaderProps) {
  const now = useClock();

  return (
    <header className="bg-techSurface border-b border-techBorder px-4 py-3 flex flex-wrap items-center justify-between gap-2 shadow-card-glow flex-shrink-0">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {onBack && (
          <>
            <button
              onClick={onBack}
              className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-techMuted hover:text-techText transition-colors min-h-[44px]"
            >
              <ArrowLeft size={14} />
              返回 / Back
            </button>
            <div className="w-px h-5 bg-techBorder shrink-0" />
          </>
        )}
        <div className="w-8 h-8 rounded-lg bg-techCyan/20 border border-techCyan/30 flex shrink-0 items-center justify-center">
          <Cpu size={14} className="text-techCyan" />
        </div>
        <div className="min-w-0">
          <div className="flex items-baseline gap-1.5">
            <span className="text-sm font-bold text-techText">
              座位 {seatId}
            </span>
            <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techMuted">
              / Seat {seatId}
            </span>
          </div>
          {meetingTitle && (
            <p className="text-xs text-techMuted truncate max-w-[200px] sm:max-w-[300px] leading-tight">
              {meetingTitle}
            </p>
          )}
          {elapsedMs != null && elapsedMs > 0 && (
            <p className="text-[0.6rem] text-techMuted/70 mt-0.5">
              {formatDuration(elapsedMs)} 已进行 / Elapsed
            </p>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <ConnectionBadge status={connection} />
        <span className="text-xs font-mono text-techMuted">
          {formatTime(now)}
        </span>
        {onMaintenanceHoldStart && onMaintenanceHoldEnd && (
          <button
            type="button"
            data-testid="maintenance-access"
            aria-label="SmartDesk 调试入口，长按 5 秒"
            title="SmartDesk 调试入口（长按 5 秒）"
            onPointerDown={onMaintenanceHoldStart}
            onPointerUp={onMaintenanceHoldEnd}
            onPointerCancel={onMaintenanceHoldEnd}
            onPointerLeave={onMaintenanceHoldEnd}
            onContextMenu={(event) => event.preventDefault()}
            className="flex h-8 w-8 shrink-0 touch-none select-none items-center justify-center rounded-lg border border-techCyan/30 bg-techCyan/10 text-techCyan transition-colors hover:bg-techCyan/20"
          >
            <Cpu size={13} />
          </button>
        )}
      </div>
    </header>
  );
}

// ── Connection Badge ─────────────────────────────────────────────────────────

function ConnectionBadge({
  status,
}: {
  status: "connecting" | "connected" | "disconnected";
}) {
  if (status === "connected") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-techGreen bg-techGreen/10 border border-techGreen/30 rounded-full px-2.5 py-1">
        <Wifi size={10} />
        在线 / Online
      </span>
    );
  }
  if (status === "connecting") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-techAmber bg-techAmber/10 border border-techAmber/30 rounded-full px-2.5 py-1">
        <Loader2 size={10} className="animate-spin" />
        连接中 / Connecting
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-techRose bg-techRose/10 border border-techRose/30 rounded-full px-2.5 py-1">
      <WifiOff size={10} />
      离线 / Offline
    </span>
  );
}

// ── Current Topic Card (read-only) ─────────────────────────────────────────────

function CurrentTopicCard({
  agendaState,
}: {
  agendaState: ReturnType<typeof deriveAgendaState>;
}) {
  const { current, progress, isFlowDone } = agendaState;

  let statusLabelCn: string;
  let statusLabelEn: string;

  if (current) {
    statusLabelCn = "进行中";
    statusLabelEn = "ACTIVE";
  } else if (isFlowDone) {
    statusLabelCn = "所有议题已处理";
    statusLabelEn = "ALL TOPICS PROCESSED";
  } else {
    statusLabelCn = "暂无当前议题";
    statusLabelEn = "NO ACTIVE TOPIC";
  }

  const progressText = progress.total > 0
    ? `${progress.current_index ?? progress.completed + progress.skipped} / ${progress.total}`
    : null;

  return (
    <PanelCard
      titleCn="当前议题"
      titleEn="CURRENT TOPIC"
      icon={<List size={16} />}
      variant={current ? "active" : "default"}
      headerRight={
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-techMuted">
          <span
            className={cx(
              "w-1.5 h-1.5 rounded-full",
              current ? "bg-techCyan animate-pulse" : "bg-techMuted",
            )}
          />
          <span className="font-semibold text-techText">{statusLabelCn}</span>
          <span className="text-[0.65rem] font-mono uppercase tracking-wider opacity-60">
            {statusLabelEn}
          </span>
        </span>
      }
    >
      {current ? (
        <div>
          <p className="text-base font-bold text-techText mb-1">
            {current.title}
          </p>
          {progressText && (
            <p className="text-xs text-techMuted">
              议程进度 / Progress: {progressText}
            </p>
          )}
        </div>
      ) : (
        <div>
          <p className="text-sm text-techMuted">
            {statusLabelCn}
          </p>
          <p className="text-[0.65rem] font-mono uppercase tracking-wider text-techMuted/60 mt-0.5">
            {statusLabelEn}
          </p>
          {progressText && (
            <p className="text-xs text-techMuted mt-2">
              议程进度 / Progress: {progressText}
            </p>
          )}
        </div>
      )}
    </PanelCard>
  );
}

// ── Seat Status Card ─────────────────────────────────────────────────────────

interface BilingualCopy {
  cn: string;
  en: string;
}

function identityStatusCopy(status: string | undefined): BilingualCopy {
  switch (status) {
    case "VERIFYING":
      return { cn: "正在验证", en: "VERIFYING" };
    case "WAITING_FOR_FACE":
      return { cn: "等待人脸", en: "WAITING FOR FACE" };
    case "MULTIPLE_FACES":
      return { cn: "检测到多人", en: "MULTIPLE FACES" };
    case "VERIFIED":
      return { cn: "已验证", en: "VERIFIED" };
    case "UNRECOGNIZED":
      return { cn: "未识别", en: "NOT RECOGNIZED" };
    case "FAILED":
      return { cn: "验证失败", en: "VERIFICATION FAILED" };
    case "UNKNOWN":
      return { cn: "身份未知", en: "UNKNOWN" };
    case "RETRY_REQUIRED":
      return { cn: "请重新识别", en: "RETRY REQUIRED" };
    case "CALIBRATION_PENDING":
      return { cn: "等待标定", en: "CALIBRATION PENDING" };
    case "NOT_ENROLLED":
      return { cn: "未注册人脸", en: "NOT ENROLLED" };
    case "ERROR":
      return { cn: "配置错误", en: "ERROR" };
    case "UNAVAILABLE":
      return { cn: "不可用", en: "UNAVAILABLE" };
    default:
      return { cn: "状态未知", en: "UNKNOWN" };
  }
}

function verificationLevelCopy(level: string | undefined): BilingualCopy | null {
  switch (level) {
    case "VALIDATED":
      return { cn: "已验证", en: "VALIDATED" };
    case "PROTOTYPE":
      return { cn: "原型验证", en: "PROTOTYPE" };
    case "NONE":
      return { cn: "未验证", en: "NONE" };
    default:
      return null;
  }
}

interface SeatStatusCardProps {
  seatId: number;
  isSpeaker: boolean;
  myAttendee: { name: string | null; title: string | null } | null;
  demoControlsEnabled: boolean;
  onVacate: () => void;
  writesAllowed: boolean;
  meetingStatus: "no_meeting" | "meeting_active";
  tabletVacateAvailable: boolean;
  onTabletVacate: () => void;
  tabletVacateSubmitting: boolean;
}

interface NativeIdentityPanelProps {
  automatic: boolean;
  status: NativeIdentityStatus | null;
  onFaceVerification: () => void;
  onStopFaceVerification: () => void;
}

function NativeIdentityPanel({
  automatic,
  status,
  onFaceVerification,
  onStopFaceVerification,
}: NativeIdentityPanelProps) {
  const verificationActive = ACTIVE_IDENTITY_STATUSES.has(
    status?.status ?? "",
  );
  const similarity =
    status?.similarity == null
      ? null
      : Number(status.similarity).toFixed(3);
  const verificationLevel = verificationLevelCopy(
    status?.verificationLevel,
  );

  return (
    <div
      data-testid="native-identity-panel"
      className="rounded-lg border border-techCyan/30 bg-techCyan/5 p-3 text-left"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <DualLabel
            cn={automatic ? "自动人脸入座" : "Android 本地身份验证"}
            en={automatic ? "AUTOMATIC FACE CHECK-IN" : "ANDROID IDENTITY VERIFICATION"}
            cnClassName="text-xs"
            enClassName="text-[0.6rem]"
          />
          <p className="mt-1 text-xs text-techMuted">
            {status?.message
              ? `设备提示 / Device message: ${status.message}`
              : automatic
                ? "正在自动等待已登记的参会人。 / Waiting for a registered attendee."
                : "请启动本地身份验证。 / Start local identity verification."}
          </p>
          {status && (
            <p className="mt-2 text-xs font-mono text-techCyan">
              {identityStatusCopy(status.status).cn} / {identityStatusCopy(status.status).en}
              {status.personId
                ? ` · 人员编号 ${status.personId} / Person ID ${status.personId}`
                : ""}
              {similarity ? ` · 相似度 ${similarity} / Similarity ${similarity}` : ""}
              {verificationLevel
                ? ` · ${verificationLevel.cn} / ${verificationLevel.en}`
                : ""}
            </p>
          )}
        </div>
        {!automatic && (
          <div className="flex flex-wrap gap-2">
            <ActionButton
              variant="primary"
              size="sm"
              touch
              icon={<UserCheck size={14} />}
              onClick={onFaceVerification}
              disabled={verificationActive}
            >
              身份验证 / Verify Identity
            </ActionButton>
            {verificationActive && (
              <ActionButton
                variant="secondary"
                size="sm"
                touch
                onClick={onStopFaceVerification}
              >
                停止 / Stop
              </ActionButton>
            )}
          </div>
        )}
      </div>
      {status?.status === "VERIFIED" && (
        <p className="mt-2 text-[0.65rem] text-techMuted">
          后端正在校验席位分配并完成入座和签到。 / The server is validating the seat assignment and check-in.
        </p>
      )}
    </div>
  );
}

function SeatStatusCard({
  seatId,
  isSpeaker,
  myAttendee,
  demoControlsEnabled,
  onVacate,
  writesAllowed,
  meetingStatus,
  tabletVacateAvailable,
  onTabletVacate,
  tabletVacateSubmitting,
}: SeatStatusCardProps) {
  return (
    <div
      className={cx(
        "bg-techCard border rounded-lg p-5 shadow-card-glow",
        isSpeaker
          ? "border-techCyan shadow-cyan-glow"
          : "border-techBorder",
      )}
    >
      <div className="flex flex-wrap items-center gap-3">
        <div
          className={cx(
            "w-14 h-14 rounded-full flex items-center justify-center text-techBg text-sm font-bold",
            isSpeaker
              ? "bg-techCyan ring-2 ring-techCyan/50 shadow-cyan-glow"
              : "bg-techGreen",
          )}
        >
          {myAttendee?.name
            ? myAttendee.name
                .split(" ")
                .slice(0, 2)
                .map((n) => n[0])
                .join("")
            : seatId}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-base font-bold text-techText">
            {myAttendee?.name ?? `座位 ${seatId} / Seat ${seatId}`}
          </p>
          <p className="text-sm text-techMuted">
            {myAttendee?.title ?? "参会人 / Attendee"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {isSpeaker && (
            <StatusBadge
              status="speaking"
              labelCn="发言中"
              labelEn="Speaking"
              icon={<Mic size={12} />}
              pulse
            />
          )}
          <StatusBadge
            status="success"
            labelCn="已签到"
            labelEn="Checked In"
            icon={<UserCheck size={12} />}
          />
        </div>
      </div>

      {(tabletVacateAvailable || demoControlsEnabled) && (
        <div className="mt-4 pt-4 border-t border-techBorder">
          <div className="flex flex-wrap gap-2">
            {tabletVacateAvailable && (
              <ActionButton
                variant="secondary"
                size="sm"
                onClick={onTabletVacate}
                loading={tabletVacateSubmitting}
                disabled={tabletVacateSubmitting || !writesAllowed}
              >
                确认离席 / Confirm Vacate
              </ActionButton>
            )}
            {demoControlsEnabled && (
              <ActionButton
                variant="secondary"
                size="sm"
                onClick={onVacate}
                disabled={!canVacateSeat(meetingStatus, true, writesAllowed)}
              >
                模拟离座 / Vacate Seat (Demo)
              </ActionButton>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Seat Vote Section ────────────────────────────────────────────────────────

interface SeatVoteSectionProps {
  vote: {
    id: number;
    title: string;
    options: string[];
    status: "open" | "closed";
    is_anonymous: boolean;
  };
  voteStats: VoteStatistics;
  voteStatsError: string | null;
  currentVote: string | null;
  selectedOption: string | null;
  onSelectOption: (option: string | null) => void;
  onSubmit: () => void;
  submitting: boolean;
  writesAllowed: boolean;
  meetingStatus: "no_meeting" | "meeting_active";
}

function SeatVoteSection({
  vote,
  voteStats,
  voteStatsError,
  currentVote,
  selectedOption,
  onSelectOption,
  onSubmit,
  submitting,
  writesAllowed,
  meetingStatus,
}: SeatVoteSectionProps) {
  const hasVoted = currentVote != null;
  const isClosed = vote.status === "closed";

  return (
    <PanelCard
      titleCn={isClosed ? "投票结果" : "当前投票"}
      titleEn={isClosed ? "Final Result" : "Active Vote"}
      icon={<Vote size={16} />}
      variant={isClosed ? "default" : "active"}
      headerRight={
        <StatusBadge
          status={isClosed ? "neutral" : "waiting"}
          labelCn={isClosed ? "已关闭" : vote.is_anonymous ? "匿名" : "公开"}
          labelEn={isClosed ? "Closed" : vote.is_anonymous ? "Anonymous" : "Open"}
        />
      }
    >
      <p className="text-sm font-semibold text-techText mb-3">
        {vote.title}
      </p>

      {/* Statistics bars (read-only) */}
      <div className="mb-4 space-y-2">
        {voteStats.results.map((opt) => {
          const pct =
            voteStats.total_votes > 0
              ? Math.round((opt.count / voteStats.total_votes) * 100)
              : 0;
          return (
            <div
              key={opt.option}
              className="flex items-center gap-2 text-xs"
            >
              <span className="w-20 min-w-0 truncate text-techText font-medium text-right sm:w-24">
                {opt.option}
              </span>
              <div className="flex-1 h-2 bg-techCardSoft rounded-full overflow-hidden">
                <div
                  className={cx(
                    "h-full rounded-full transition-all duration-500",
                    isClosed ? "bg-techMuted" : "bg-techCyan",
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="w-20 shrink-0 text-techMuted">
                {opt.count} / {pct}%
              </span>
            </div>
          );
        })}
      </div>

      {voteStatsError && (
        <div className="mb-3 bg-techAmber/10 border border-techAmber/30 rounded-lg px-3 py-2 flex items-center gap-2">
          <AlertCircle size={12} className="text-techAmber flex-shrink-0" />
          <p className="text-xs text-techAmber">{voteStatsError}</p>
        </div>
      )}

      <p className="mb-4 text-xs text-techMuted">
        共 {voteStats.total_votes} 票 / {voteStats.total_votes} vote{voteStats.total_votes !== 1 ? "s" : ""} cast
      </p>

      {/* Vote option selection */}
      <div className="space-y-1.5 mb-3">
        {vote.options.map((option) => {
          const isSelected = selectedOption === option;
          const isMyVote = currentVote === option;
          return (
            <button
              key={option}
              onClick={() => onSelectOption(isSelected ? null : option)}
              disabled={!canSelectVoteOption(meetingStatus, vote.status, writesAllowed)}
              className={cx(
                "w-full flex items-center gap-3 rounded-lg border px-4 py-3 min-h-[48px] text-left transition-all duration-150 active:scale-[0.98]",
                isSelected
                  ? "border-techCyan bg-techCyan/10"
                  : isMyVote
                    ? "border-techGreen bg-techGreen/10"
                    : "border-techBorder bg-techCard hover:bg-techCardSoft",
                "disabled:opacity-40 disabled:cursor-not-allowed",
              )}
            >
              <div
                className={cx(
                  "w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0",
                  isSelected
                    ? "border-techCyan"
                    : isMyVote
                      ? "border-techGreen"
                      : "border-techMuted",
                )}
              >
                {(isSelected || isMyVote) && (
                  <div
                    className={cx(
                      "w-2.5 h-2.5 rounded-full",
                      isSelected ? "bg-techCyan" : "bg-techGreen",
                    )}
                  />
                )}
              </div>
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-techText">
                {option}
              </span>
              {isMyVote && (
                <span className="shrink-0 text-xs text-techGreen font-medium">
                  已投 / Your vote
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        {!isClosed && (
          <ActionButton
            variant="primary"
            size="lg"
            touch
            icon={submitting ? undefined : <CheckCircle2 size={16} />}
            onClick={onSubmit}
            disabled={!canSubmitVote(meetingStatus, vote.status, true, !!selectedOption, writesAllowed) || submitting}
            loading={submitting}
          >
            {hasVoted ? "更新投票 / Update Vote" : "提交投票 / Submit Vote"}
          </ActionButton>
        )}
        {hasVoted && (
          <p className="text-xs text-techMuted">
            <span>你的选择 / </span>
            <span>Your choice:</span>{" "}
            <span className="font-semibold text-techText">{currentVote}</span>
          </p>
        )}
        {isClosed && !hasVoted && (
          <p className="text-xs text-techMuted">
            此投票结果不显示你的选择。 / Your choice is unavailable for this result.
          </p>
        )}
      </div>
    </PanelCard>
  );
}

// ── Seat Service Section ─────────────────────────────────────────────────────

const SERVICE_TYPES: Array<{
  type: ServiceType;
  label: string;
  labelCn: string;
  icon: React.ReactNode;
  color: string;
}> = [
  {
    type: "coffee",
    label: "Coffee",
    labelCn: "咖啡",
    icon: <Coffee size={18} />,
    color: "text-techAmber border-techAmber/30 hover:bg-techAmber/10",
  },
  {
    type: "tea",
    label: "Tea",
    labelCn: "茶水",
    icon: <Leaf size={18} />,
    color: "text-techGreen border-techGreen/30 hover:bg-techGreen/10",
  },
  {
    type: "water",
    label: "Water",
    labelCn: "矿泉水",
    icon: <Droplets size={18} />,
    color: "text-techCyan border-techCyan/30 hover:bg-techCyan/10",
  },
  {
    type: "other",
    label: "Other",
    labelCn: "其他",
    icon: <MoreHorizontal size={18} />,
    color: "text-techMuted border-techBorder hover:bg-techCardSoft",
  },
];

interface SeatServiceSectionProps {
  currentCall: {
    id: number;
    service_type: ServiceType;
    status: string;
  } | null;
  onRequest: (type: ServiceType) => void;
  onCancel: () => void;
  creating: boolean;
  cancelling: boolean;
  writesAllowed: boolean;
  meetingStatus: "no_meeting" | "meeting_active";
}

function SeatServiceSection({
  currentCall,
  onRequest,
  onCancel,
  creating,
  cancelling,
  writesAllowed,
  meetingStatus,
}: SeatServiceSectionProps) {
  const hasPending = currentCall?.status === "pending";

  return (
    <PanelCard
      titleCn="服务请求"
      titleEn="Service Request"
      icon={<Coffee size={16} />}
    >
      {hasPending ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-techAmber/30 bg-techAmber/10 px-4 py-3 min-h-[48px]">
          <Clock size={18} className="text-techAmber flex-shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-techText">
              {SERVICE_TYPES.find(
                (s) => s.type === currentCall.service_type,
              )?.labelCn ?? currentCall.service_type}{" "}
              — <span className="text-techAmber">待处理 / Pending</span>
            </p>
            <p className="text-xs text-techMuted">
              请求已发送 / Your request has been sent
            </p>
          </div>
          <ActionButton
            variant="danger"
            size="md"
            touch
            icon={cancelling ? undefined : <XCircle size={14} />}
            onClick={onCancel}
            disabled={!canCancelService(meetingStatus, hasPending, writesAllowed) || cancelling}
            loading={cancelling}
          >
            取消 / Cancel
          </ActionButton>
        </div>
      ) : (
        <>
          <p className="text-xs text-techMuted mb-3">
            选择服务 / Request a service:
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {SERVICE_TYPES.map((svc) => (
              <button
                key={svc.type}
                onClick={() => onRequest(svc.type)}
                disabled={!canCallService(meetingStatus, true, hasPending, writesAllowed) || creating}
                className={cx(
                  "flex items-center gap-3 rounded-lg border px-4 py-3 min-h-[48px]",
                  "text-sm font-medium transition-all duration-150 active:scale-[0.98]",
                  "bg-techCard",
                  svc.color,
                  "disabled:opacity-40 disabled:cursor-not-allowed",
                )}
              >
                {svc.icon}
                <span className="flex items-baseline gap-1.5">
                  <span>{svc.labelCn}</span>
                  <span className="text-[0.6rem] font-mono uppercase tracking-wider opacity-60">
                    {svc.label}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </PanelCard>
  );
}

// ── Speech Control ────────────────────────────────────────────────────────────

interface SpeechControlProps {
  meetingId: number | null;
  seatId: number;
  isSpeaker: boolean;
  isCheckedIn: boolean;
  writesAllowed: boolean;
  meetingStatus: "no_meeting" | "meeting_active";
  /** Task 127A: local cleanup callback — immediately removes live caption. */
  onLocalTerminalUtterance?: (utteranceId: string, reason: string) => void;
}

function SpeechControl({
  meetingId,
  seatId,
  isSpeaker,
  isCheckedIn,
  writesAllowed,
  meetingStatus,
  onLocalTerminalUtterance,
}: SpeechControlProps) {
  const {
    status,
    error,
    languageMode,
    setLanguageMode,
    start,
    stop,
    cancel,
  } = useSpeechStream(
    meetingId,
    seatId,
    isSpeaker,
    onLocalTerminalUtterance ? { onLocalTerminalUtterance } : undefined,
  );

  // ── Speech model status polling (Task 119) ──────────────────────────────
  const [speechStatus, setSpeechStatus] = useState<SpeechModelStatus | null>(null);
  const [speechStatusError, setSpeechStatusError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const poll = async () => {
      try {
        const s = await fetchSpeechStatus();
        setSpeechStatus(s);
        setSpeechStatusError(null);
      } catch (err) {
        setSpeechStatusError(err instanceof Error ? err.message : "Failed to fetch speech status");
      }
    };
    // Initial fetch
    poll();
    // Poll every 5 seconds
    pollRef.current = setInterval(poll, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const modelsReady = speechStatus?.ready ?? false;
  const modelsPreloading = speechStatus?.preloading ?? false;
  const chinesePunctuationUnavailable =
    !modelsPreloading &&
    languageMode !== "en" &&
    speechStatus?.punctuation_model === "error";
  const englishPunctuationUnavailable =
    !modelsPreloading &&
    languageMode !== "zh" &&
    speechStatus?.english_online_punctuation?.status === "error";
  const translationReady = speechStatus?.translation_model === "loaded";
  const unavailableDirections = Object.entries(speechStatus?.translation_models ?? {})
    .filter(([, model]) => model.status !== "loaded")
    .map(([direction, model]) => `${direction.replace("_", "→").toUpperCase()}${model.error ? `：${model.error}` : ""}`);
  const translationError = unavailableDirections.join("；") || speechStatus?.translation_last_error || null;

  const browserSupportsMic =
    typeof navigator !== "undefined" && isMicrophoneCaptureSupported();

  const startDisabled =
    !canStartSpeech(meetingStatus, isSpeaker, isCheckedIn, writesAllowed, modelsReady, browserSupportsMic) ||
    status === "requesting_microphone" ||
    status === "connecting_speech_ws";

  // ── Non-speaker seat: read-only hint ────────────────────────────────────
  if (!isSpeaker) {
    return (
      <PanelCard
        icon={<MicOff size={16} />}
        className="border-dashed"
      >
        <SectionHeader
          titleCn="语音识别"
          titleEn="Speech Recognition"
          icon={<Mic size={14} />}
        />
        <p className="text-xs text-techMuted mt-2">
          仅发言席可传输音频。 / Only the speaker seat can stream audio.
        </p>
      </PanelCard>
    );
  }

  // ── Speaker seat: controls ─────────────────────────────────────────────
  return (
    <PanelCard
      titleCn="语音识别"
      titleEn="Speech Recognition"
      icon={<Mic size={16} />}
      variant={status === "recording" ? "active" : "default"}
      headerRight={
        <div className="flex flex-wrap justify-end gap-1">
          {status === "recording" && (
            <StatusBadge
              status="danger"
              labelCn="正在识别"
              labelEn="Recording"
              icon={<Mic size={10} />}
              pulse
            />
          )}
          {modelsPreloading && (
            <StatusBadge
              status="waiting"
              labelCn="模型加载中"
              labelEn="Loading models"
              icon={<Loader2 size={10} />}
            />
          )}
        </div>
      }
    >
      {/* Speech status error (API fetch failure) */}
      {speechStatusError && (
        <div className="mb-3 bg-techAmber/10 border border-techAmber/30 rounded-lg px-3 py-2 flex items-start gap-2">
          <AlertCircle size={14} className="text-techAmber flex-shrink-0 mt-0.5" />
          <p className="text-xs text-techAmber">{speechStatusError}</p>
        </div>
      )}

      {/* Speech module not ready */}
      {!modelsReady && !modelsPreloading && status === "idle" && (
        <div className="mb-3 bg-techAmber/10 border border-techAmber/30 rounded-lg px-3 py-2 flex items-start gap-2">
          <Loader2 size={14} className="text-techAmber flex-shrink-0 mt-0.5 animate-spin" />
          <p className="text-xs text-techAmber">
            <span>语音模型加载中… / </span>
            <span>Speech models loading...</span>
          </p>
        </div>
      )}

      {/* Language-specific punctuation fallback hints (non-blocking). */}
      {chinesePunctuationUnavailable && status !== "recording" && status !== "error" && status !== "requesting_microphone" && status !== "connecting_speech_ws" && (
        <div className="mb-3 bg-techAmber/10 border border-techAmber/30 rounded-lg px-3 py-1.5 flex items-start gap-2">
          <AlertCircle size={12} className="text-techAmber flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-techAmber">
            <span>中文标点模型不可用，已启用基础回退。 / </span>
            <span>Chinese punctuation model unavailable — basic fallback active</span>
          </p>
        </div>
      )}

      {englishPunctuationUnavailable && status !== "recording" && status !== "error" && status !== "requesting_microphone" && status !== "connecting_speech_ws" && (
        <div className="mb-3 bg-techAmber/10 border border-techAmber/30 rounded-lg px-3 py-1.5 flex items-start gap-2">
          <AlertCircle size={12} className="text-techAmber flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-techAmber">
            英文标点模型不可用，已启用无标点回退。 / English punctuation model unavailable — unpunctuated fallback active.
          </p>
        </div>
      )}

      {!translationReady && !modelsPreloading && status === "idle" && (
        <div className="mb-3 bg-techAmber/10 border border-techAmber/30 rounded-lg px-3 py-1.5 flex items-start gap-2">
          <AlertCircle size={12} className="text-techAmber flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-techAmber">
            {translationError
              ? `中英翻译模型不可用：${translationError}`
              : "中英双向翻译模型尚未就绪 / Chinese–English translation models are not ready"}
          </p>
        </div>
      )}

      <fieldset className="mb-3" disabled={status !== "idle"}>
        <legend className="mb-1.5 text-[11px] text-techMuted">
          识别语言 / Recognition language
        </legend>
        <div
          className="grid grid-cols-3 gap-1 rounded-lg border border-techCyan/20 bg-techCardSoft p-1"
          data-testid="speech-language-selector"
        >
          {([
            ["auto", "自动 / Auto"],
            ["zh", "中文 / Chinese"],
            ["en", "英文 / English"],
          ] as const).map(([mode, label]) => (
            <button
              type="button"
              key={mode}
              aria-pressed={languageMode === mode}
              onClick={() => setLanguageMode(mode)}
              className={`rounded px-2 py-1.5 text-xs transition-colors ${
                languageMode === mode
                  ? "bg-techCyan/20 text-techCyan"
                  : "text-techMuted hover:text-techText"
              } disabled:cursor-not-allowed disabled:opacity-50`}
            >
              {label}
            </button>
          ))}
        </div>
      </fieldset>

      {/* Error */}
      {status === "error" && error && (
        <div className="mb-3 bg-techRose/10 border border-techRose/30 rounded-lg px-3 py-2 flex items-start gap-2">
          <AlertCircle size={14} className="text-techRose flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-xs text-techRose">{error}</p>
            <button
              onClick={cancel}
              className="text-xs font-medium text-techRose underline mt-1 hover:text-techRose/80"
            >
              关闭 / Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Status text */}
      <div className="mb-3 text-xs text-techMuted space-y-1">
        {status === "idle" && modelsReady && (
          <p>
            <span className="text-techGreen font-medium">
              准备就绪 / Ready
            </span>{" "}
            — 点击开始即可发言 / Click Start to begin speaking
          </p>
        )}
        {status === "idle" && !modelsReady && (
          <p className="text-techAmber">
            <span>正在等待语音模型… / </span>
            <span>Waiting for speech models...</span>
          </p>
        )}
        {status === "requesting_microphone" && (
          <p className="text-techAmber">
            正在请求麦克风权限… / Requesting microphone access...
          </p>
        )}
        {status === "connecting_speech_ws" && (
          <p className="text-techAmber">
            正在连接语音服务… / Connecting to speech service...
          </p>
        )}
        {status === "recording" && (
          <p className="text-techGreen font-medium">
            <span>正在传输音频… / </span>
            <span>Streaming audio...</span>
          </p>
        )}
        {status === "stopping" && (
          <p className="text-techMuted">
            <span>正在停止… / </span>
            <span>Stopping...</span>
          </p>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap items-center gap-2">
        {status === "idle" && (
          <ActionButton
            variant="primary"
            size="lg"
            touch
            icon={<Mic size={16} />}
            onClick={start}
            disabled={startDisabled}
          >
            <span className="flex items-baseline gap-1.5">
              <span>开始识别</span>
              <span className="text-[0.6rem] font-mono uppercase tracking-wider opacity-60">Start</span>
            </span>
          </ActionButton>
        )}
        {status === "recording" && (
          <>
            <ActionButton
              variant="secondary"
              size="lg"
              touch
              icon={<Square size={16} />}
              onClick={stop}
            >
              <span className="flex items-baseline gap-1.5">
                <span>停止</span>
                <span className="text-[0.6rem] font-mono uppercase tracking-wider opacity-60">Stop</span>
              </span>
            </ActionButton>
            <ActionButton
              variant="danger"
              size="lg"
              touch
              icon={<XCircle size={16} />}
              onClick={cancel}
            >
              <span className="flex items-baseline gap-1.5">
                <span>取消</span>
                <span className="text-[0.6rem] font-mono uppercase tracking-wider opacity-60">Cancel</span>
              </span>
            </ActionButton>
          </>
        )}
        {status === "error" && (
          <ActionButton
            variant="primary"
            size="lg"
            touch
            icon={<RefreshCw size={16} />}
            onClick={cancel}
          >
            <span className="flex items-baseline gap-1.5">
              <span>重试</span>
              <span className="text-[0.6rem] font-mono uppercase tracking-wider opacity-60">Retry</span>
            </span>
          </ActionButton>
        )}
      </div>

      {/* Model not ready tooltip */}
      {status === "idle" && !modelsReady && !modelsPreloading && (
        <p className="mt-2 text-xs text-techAmber">
          语音识别模型正在加载，完成后即可开始。 / Speech recognition models are being loaded. Start will be available once ready.
        </p>
      )}

      {/* Mic not supported warning */}
      {!browserSupportsMic && (
        <p className="mt-2 text-xs text-techAmber">
          此浏览器不支持麦克风。 / Microphone is not supported in this browser.
        </p>
      )}
    </PanelCard>
  );
}
