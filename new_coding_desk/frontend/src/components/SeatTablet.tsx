import {
  useCallback,
  useState,
  useMemo,
  useEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  Cpu,
  ArrowLeft,
  Captions,
  ChevronDown,
  Presentation,
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
import { isDemoControlsEnabled } from "./shared";
import { useSpeechStream } from "../hooks/useSpeechStream";
import { isMicrophoneCaptureSupported } from "../audio/microphone";
import type { SpeechStatus } from "../audio/types";
import { TranscriptPanel } from "./TranscriptPanel";
import { SpatialStage } from "../spatial/SpatialStage";
import type { SceneSeat, SpatialState } from "../spatial/sceneState";
import {
  identityCheckinSeat,
  manualAdmitSeat,
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
import "./seat-focus.css";

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
const SEAT_VIEWS = [
  { id: "room", cn: "会场", en: "Room", icon: Presentation },
  { id: "captions", cn: "字幕", en: "Captions", icon: Captions },
  { id: "vote", cn: "投票", en: "Vote", icon: Vote },
  { id: "service", cn: "服务", en: "Service", icon: Coffee },
] as const;
type SeatView = typeof SEAT_VIEWS[number]["id"];

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
  const [localSpeechStatus, setLocalSpeechStatus] = useState<SpeechStatus>("idle");
  const [activeView, setActiveView] = useState<SeatView>("room");
  const tabButtons = useRef<Partial<Record<SeatView, HTMLButtonElement | null>>>({});
  const viewScroll = useRef<HTMLElement>(null);
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
  const assignedAttendee = attendees.find((attendee) => attendee.assigned_seat_id === seatId)
    ?? attendees.find((attendee) =>
      attendee.assigned_seat_id == null && attendee.checked_in
      && attendee.id === mySeat?.attendeeId && attendee.seat_id === seatId)
    ?? null;
  const demoBrowser = isDemoControlsEnabled() && !nativeBridge.isAvailable();
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
  const displayVoteStats = activeVote ? voteStats : latestClosedVote;
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

  const myAttendeeId = mySeat?.attendeeId ?? null;
  const recordedVote = displayVoteStats?.results
    .find((result) => myAttendeeId != null && result.attendee_ids?.includes(myAttendeeId))
    ?.option ?? null;
  const [voteReceipt, setVoteReceipt] = useState<{ voteId: number; attendeeId: number; option: string } | null>(null);
  const currentVoteOption = voteReceipt?.voteId === displayVote?.id
    && voteReceipt?.attendeeId === myAttendeeId ? voteReceipt?.option ?? null : recordedVote;

  useEffect(() => {
    setActiveView("room");
  }, [meeting?.id, meetingAccessGranted]);

  function selectView(view: SeatView, focusTab = false) {
    setActiveView(view);
    if (viewScroll.current) viewScroll.current.scrollTop = 0;
    if (focusTab) tabButtons.current[view]?.focus();
  }

  function navigateTabs(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    switch (event.key) {
      case "ArrowLeft": next = (index + SEAT_VIEWS.length - 1) % SEAT_VIEWS.length; break;
      case "ArrowRight": next = (index + 1) % SEAT_VIEWS.length; break;
      case "Home": next = 0; break;
      case "End": next = SEAT_VIEWS.length - 1; break;
      default: return;
    }
    event.preventDefault();
    selectView(SEAT_VIEWS[next].id, true);
  }

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
    if (!writesAllowed || !selectedVoteOption || myAttendeeId == null) return;
    setSubmittingVote(true);
    setActionError(null);
    try {
      await submitVote(
        activeVote.id,
        myAttendeeId,
        selectedVoteOption,
      );
      setVoteReceipt({ voteId: activeVote.id, attendeeId: myAttendeeId, option: selectedVoteOption });
      setSelectedVoteOption(null);
      await refresh();
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

  const checkingInRef = useRef(false);
  async function handleDemoCheckIn() {
    if (!demoBrowser || !writesAllowed || !assignedAttendee || checkingInRef.current) return;
    checkingInRef.current = true;
    setIdentityCheckinSubmitting(true);
    setActionError(null);
    try {
      await manualAdmitSeat(seatId);
      await refresh();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "演示签到失败");
    } finally {
      checkingInRef.current = false;
      setIdentityCheckinSubmitting(false);
    }
  }

  // ── Whether writes are allowed (Task 4) ─────────────────────────────────

  const meetingStatus = deriveSeatMeetingStatus(meeting);
  const writesAllowed =
    wsConnected && !error && !!meeting && meeting?.status === "active";
  useEffect(() => {
    setSelectedVoteOption(null);
    setVoteReceipt(null);
  }, [meeting?.id, myAttendeeId]);

  useEffect(() => {
    setSelectedVoteOption(null);
  }, [activeVote?.id]);

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

  const waitingForMeeting = loading || (error && !meeting) || noMeeting;
  const header = (
    <SeatHeader
      seatId={seatId}
      onBack={onSwitchToAdmin}
      meetingTitle={waitingForMeeting ? undefined : meeting?.title}
      actions={!waitingForMeeting && meetingAccessGranted && (
        <SeatOptions
          demoControlsEnabled={demoBrowser}
          onVacate={handleVacate}
          writesAllowed={writesAllowed}
          meetingStatus={meetingStatus}
          tabletVacateAvailable={tabletVacateAvailable}
          onTabletVacate={handleTabletVacate}
          tabletVacateSubmitting={tabletVacateSubmitting}
        />
      )}
      onMaintenanceHoldStart={maintenanceAccessAvailable ? beginMaintenanceHold : undefined}
      onMaintenanceHoldEnd={maintenanceAccessAvailable ? cancelMaintenanceHold : undefined}
    />
  );

  if (waitingForMeeting) {
    const phase = loading ? "busy" : error ? "fault" : "idle";
    return (
      <div data-spatial-mode="station" data-spatial-phase={phase} className="desk-page flex min-h-dvh flex-col">
        {header}
        <main className="grid flex-1 place-items-center p-4 sm:p-6">
          <div className="desk-panel grid w-full max-w-5xl overflow-hidden md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <div className="relative min-h-48 md:min-h-[24rem]">
              <div className="absolute inset-0">
                <SpatialStage
                  className="spatial-gate-stage h-full w-full"
                  state={{ mode: "station", phase, selectedSeat: seatId }}
                />
              </div>
            </div>
            <div className="spatial-gate-card flex flex-col items-center justify-center gap-4 border-t border-techBorder p-6 text-center sm:p-8 md:items-start md:border-l md:border-t-0 md:text-left">
              {loading ? (
                <>
                  <Loader2 size={30} className="animate-spin text-techCyan" />
                  <p className="text-sm font-medium text-techMuted">正在加载席位数据 / Loading seat data...</p>
                </>
              ) : error ? (
                <>
                  <div className="desk-brand-mark grid h-14 w-14 place-items-center">
                    <Loader2 className="animate-spin text-techCyan" size={24} />
                  </div>
                  <p className="text-xl font-semibold text-techText">正在重新连接会议系统 / Reconnecting</p>
                  <p className="break-words text-xs text-techMuted">{error}</p>
                  <ActionButton variant="primary" size="md" icon={<RefreshCw size={14} />} onClick={refresh}>
                    <span>重试 / </span>
                    <span>Retry</span>
                  </ActionButton>
                </>
              ) : (
                <>
                  <div className="desk-brand-mark grid h-14 w-14 place-items-center">
                    <Cpu className="text-techCyan" size={24} />
                  </div>
                  <p className="text-2xl font-bold text-techText">等待会议开始 / Waiting for Meeting</p>
                  <p className="text-sm text-techMuted">
                    会议开始后将自动启用此席位页面。 / The seat interface will activate once a meeting starts.
                  </p>
                  <ActionButton variant="secondary" size="md" icon={<RefreshCw size={14} />} onClick={refresh}>
                    刷新 / Refresh
                  </ActionButton>
                </>
              )}
            </div>
          </div>
        </main>
      </div>
    );
  }

  if (!meetingAccessGranted) {
    const hasAssignment = assignedAttendee != null;
    const canRecognize = nativeBridge.isAvailable() && assignedAttendee?.person_id != null;
    const verificationActive = ACTIVE_IDENTITY_STATUSES.has(
      nativeIdentityStatus?.status ?? "",
    );
    const phase = error || actionError || connection === "disconnected" ? "fault"
      : identityCheckinSubmitting || verificationActive || (hasAssignment && identityMode === "debug") ? "busy"
      : "idle";
    return (
      <div
        data-testid="seat-page-scroll"
        data-spatial-mode="identity"
        data-spatial-phase={phase}
        className="desk-page flex h-dvh flex-col overflow-y-auto"
      >
        {header}
        {error && (
          <div className="border-b border-techAmber/40 bg-techAmber/10 px-4 py-2 text-center text-xs font-semibold text-techAmber">
            连接暂时中断，正在自动重连。{error && ` · ${error}`}
          </div>
        )}
        <main
          data-testid="face-access-gate"
          className="grid flex-1 place-items-center p-4 sm:p-6"
        >
          <div className="desk-panel grid w-full max-w-5xl overflow-hidden md:grid-cols-[minmax(0,1.12fr)_minmax(0,1fr)]">
            <div className="relative min-h-48 md:min-h-[25rem]">
              <div className="absolute inset-0">
                <SpatialStage
                  className="spatial-gate-stage h-full w-full"
                  state={{
                    mode: "identity",
                    phase,
                    selectedSeat: seatId,
                    seats: [{ id: seatId, status: hasAssignment ? "assigned" : "vacant" }],
                    signal: nativeIdentityStatus?.status,
                  }}
                />
              </div>
            </div>
            <div className="spatial-gate-card grid min-w-0 content-center border-t border-techBorder p-6 text-center sm:p-8 md:border-l md:border-t-0">
              <div className="desk-brand-mark mx-auto mb-4 grid h-12 w-12 place-items-center">
                <UserCheck size={24} className="text-techCyan" />
              </div>
              <h1 className="text-2xl font-semibold text-techText sm:text-3xl">
                {demoBrowser ? "席位签到 / Seat Check-in" : "人脸验证门禁 / Face Access"}
              </h1>
              {!hasAssignment ? (
                <p className="mt-4 text-sm text-techAmber">
                  等待主持人分配席位人员 / Waiting for host seat assignment
                </p>
              ) : demoBrowser ? (
                <div className="mt-5 space-y-4">
                  <p className="text-xl font-semibold text-techText">{assignedAttendee.name}</p>
                  <p className="text-sm text-techMuted">演示模式，可直接签到。</p>
                  <ActionButton
                    variant="primary"
                    size="lg"
                    touch
                    icon={<UserCheck size={16} />}
                    onClick={() => void handleDemoCheckIn()}
                    disabled={!writesAllowed}
                    loading={identityCheckinSubmitting}
                  >
                    演示签到 / Demo Check-in
                  </ActionButton>
                </div>
              ) : identityMode === "debug" ? (
                <div className="mt-5 space-y-2">
                  <Loader2 size={28} className="mx-auto animate-spin text-techAmber" />
                  <p className="text-base font-semibold text-techText">
                    {assignedAttendee.name}
                  </p>
                  <p className="text-sm text-techAmber">
                    正在确认席位 / Confirming your seat
                  </p>
                </div>
              ) : !canRecognize ? (
                <div className="mt-4 space-y-2">
                  <p className="text-base font-semibold text-techText">
                    {assignedAttendee.name}
                  </p>
                  <p className="text-sm text-techAmber">
                    {nativeBridge.isAvailable()
                      ? "默认人员尚未绑定人脸，请联系主持人放行。"
                      : "当前浏览器无法使用平板人脸验证，请联系主持人放行。"}
                  </p>
                </div>
              ) : (
                <div className="mt-5 space-y-4 text-left">
                  <p className="text-center text-sm text-techMuted">
                    默认人员：{assignedAttendee.name}
                  </p>
                  <NativeIdentityPanel status={nativeIdentityStatus} />
                  {!verificationActive && (
                    <div className="flex justify-center">
                      <ActionButton
                        variant="primary"
                        size="md"
                        icon={<RefreshCw size={14} />}
                        onClick={() => void retryFaceVerification().catch((reason: unknown) => {
                          setActionError(reason instanceof Error ? reason.message : "重新识别失败");
                        })}
                        disabled={identityCheckinSubmitting}
                      >
                        重新识别 / Retry Recognition
                      </ActionButton>
                    </div>
                  )}
                </div>
              )}
              {actionError && (
                <p role="alert" className="mt-5 rounded-lg border border-techRose/30 bg-techRose/10 px-4 py-3 text-sm text-techRose">
                  签到失败 / Check-in failed · {actionError}
                </p>
              )}
              {!wsConnected && (
                <p className="mt-4 text-xs text-techAmber">
                  后端连接已断开，恢复连接前不会解锁会议页面。
                </p>
              )}
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ── Active Meeting ─────────────────────────────────────────────────────

  const assignedSeatIds = new Set(attendees.map((attendee) => attendee.assigned_seat_id));
  const sceneSeats = seats.map<SceneSeat>((seat) => ({
    id: seat.seatId,
    status: seat.isCheckedIn ? (seat.isSpeaker ? "speaking" : "ready")
      : seat.isVacant && !assignedSeatIds.has(seat.seatId) ? "vacant" : "assigned",
  }));
  const speechActive = (isSpeaker && ["recording", "stopping"].includes(localSpeechStatus))
    || (speakerSeatId != null && Object.values(interimMap).some((item) => item.seatId === speakerSeatId));
  const speechStarting = isSpeaker && ["requesting_microphone", "connecting_speech_ws"].includes(localSpeechStatus);
  const speechFailed = isSpeaker && localSpeechStatus === "error";
  const phase = error || actionError || speechFailed || connection === "disconnected" ? "fault"
    : !wsConnected || speechStarting ? "busy"
    : speechActive ? "speech"
    : activeVote?.status === "open" ? "vote"
    : isSpeaker ? "speech" : "live";
  const scene: SpatialState = {
    mode: "station",
    phase,
    selectedSeat: seatId,
    seats: sceneSeats,
    level: phase === "vote" ? Number(currentVoteOption != null)
      : phase === "speech" ? Number(speechActive)
      : seats.filter((seat) => seat.isCheckedIn).length / Math.max(1, seats.length),
    signal: [meeting?.id, agendaState.current?.id, speakerSeatId, displayVote?.id, displayVote?.status,
      currentVoteOption != null, isSpeaker ? localSpeechStatus : null].join(":"),
  };

  const voteOpen = displayVote?.status === "open";
  const servicePending = currentServiceCall?.status === "pending";
  const viewId = (view: SeatView) => `seat-${seatId}-view-${view}`;
  const tabId = (view: SeatView) => `seat-${seatId}-tab-${view}`;

  return (
    <div
      data-testid="seat-page-scroll"
      data-spatial-mode="station"
      data-spatial-phase={phase}
      className="desk-page seat-focus-shell"
    >
      {header}

      <div className="seat-focus-tabs" role="tablist" aria-label="席位视图 / Seat views">
        {SEAT_VIEWS.map(({ id, cn, en, icon: Icon }, index) => (
          <button
            key={id}
            id={tabId(id)}
            data-testid={`seat-tab-${id}`}
            ref={(button) => { tabButtons.current[id] = button; }}
            type="button"
            role="tab"
            aria-label={`${cn} / ${en}`}
            aria-selected={activeView === id}
            aria-controls={viewId(id)}
            aria-describedby={(id === "vote" && voteOpen) || (id === "service" && servicePending) ? `${tabId(id)}-status` : undefined}
            tabIndex={activeView === id ? 0 : -1}
            onClick={() => selectView(id)}
            onKeyDown={(event) => navigateTabs(event, index)}
          >
            <Icon size={17} aria-hidden="true" />
            <span>{cn} <small>{en}</small></span>
            {((id === "vote" && voteOpen) || (id === "service" && servicePending)) && (
              <>
                <span className="seat-focus-tab-dot" aria-hidden="true" />
                <span id={`${tabId(id)}-status`} className="sr-only">
                  {id === "vote" ? "投票进行中 / Vote open" : "服务待响应 / Service pending"}
                </span>
              </>
            )}
          </button>
        ))}
      </div>

      <div className="seat-focus-notices">
        {actionError && (
          <div role="alert" className="seat-focus-notice text-techRose">
            <AlertCircle size={16} aria-hidden="true" />
            <p>操作失败 / Operation failed · {actionError}</p>
            <button type="button" aria-label="关闭错误提示" onClick={() => setActionError(null)}>
              <XCircle size={18} aria-hidden="true" />
            </button>
          </div>
        )}
        {(!wsConnected || error) && (
          <div role="status" className="seat-focus-notice text-techAmber">
            <p>实时连接恢复中 / Reconnecting</p>
            <ActionButton variant="secondary" size="sm" touch onClick={refresh}>
              立即重试 / Retry now
            </ActionButton>
          </div>
        )}
      </div>

      <main className="seat-focus-content" ref={viewScroll}>
        <section className="seat-focus-view" role="tabpanel" id={viewId("room")} aria-labelledby={tabId("room")} hidden={activeView !== "room"} tabIndex={0}>
          {activeView === "room" && (
            <div className="seat-focus-room">
              <div className="seat-focus-brief">
                <CurrentTopicCard agendaState={agendaState} />
                <div className="seat-focus-room-actions">
                  {voteOpen && (
                    <ActionButton
                      data-testid="seat-open-vote"
                      variant="primary"
                      size="md"
                      touch
                      icon={<Vote size={17} />}
                      onClick={() => selectView("vote", true)}
                    >
                      {currentVoteOption ? "查看投票 / View vote" : "投票进行中 / Vote open"}
                    </ActionButton>
                  )}
                  <ActionButton
                    data-testid="seat-screen-entry"
                    variant="secondary"
                    size="md"
                    touch
                    icon={<Monitor size={17} />}
                    onClick={() => navigate("/screen", { state: { seatId } })}
                  >
                    共享画面 / Screen Share
                  </ActionButton>
                  {servicePending && (
                    <ActionButton
                      variant="secondary"
                      size="md"
                      touch
                      icon={<Coffee size={17} />}
                      onClick={() => selectView("service", true)}
                    >
                      服务待响应 / Service pending
                    </ActionButton>
                  )}
                </div>
                <div className="seat-focus-attendee">
                  {myAttendeeName && <span>{myAttendeeName}</span>}
                  {myAttendeeTitle && <span>{myAttendeeTitle}</span>}
                  <span className="seat-focus-confirmed">
                    <UserCheck size={15} aria-hidden="true" />
                    已签到 <span>Checked In</span>
                  </span>
                </div>
              </div>
              <div className="seat-focus-scene">
                <SpatialStage state={scene} showTitle={false} className="spatial-seat-stage h-full w-full" />
              </div>
            </div>
          )}
        </section>

        <section className="seat-focus-view seat-focus-caption" role="tabpanel" id={viewId("captions")} aria-labelledby={tabId("captions")} hidden={activeView !== "captions"} tabIndex={0}>
          {activeView === "captions" && (
            <>
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
              {!isSpeaker && (
                <p className="seat-focus-speaker-hint">
                  仅当前发言席可识别。 / Only the current speaker seat can use speech recognition.
                </p>
              )}
            </>
          )}
        </section>

        <section className="seat-focus-view seat-focus-form" role="tabpanel" id={viewId("vote")} aria-labelledby={tabId("vote")} hidden={activeView !== "vote"} tabIndex={0}>
          {activeView === "vote" && (displayVote ? (
            <SeatVoteSection
              vote={displayVote}
              voteStats={displayVoteStats}
              voteStatsError={voteStatsError}
              currentVote={currentVoteOption}
              onRetryStats={refresh}
              selectedOption={selectedVoteOption}
              onSelectOption={setSelectedVoteOption}
              onSubmit={handleVoteSubmit}
              submitting={submittingVote}
              writesAllowed={writesAllowed}
              meetingStatus={meetingStatus}
            />
          ) : (
            <div className="seat-focus-empty">
              <Vote size={26} aria-hidden="true" />
              <h2>暂无投票 <span>No vote yet</span></h2>
            </div>
          ))}
        </section>

        <section className="seat-focus-view seat-focus-form" role="tabpanel" id={viewId("service")} aria-labelledby={tabId("service")} hidden={activeView !== "service"} tabIndex={0}>
          {activeView === "service" && (
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
        </section>
      </main>

      <SpeechControl
        compact
        meetingId={meeting?.id ?? null}
        seatId={seatId}
        isSpeaker={isSpeaker}
        isCheckedIn={isCheckedIn}
        writesAllowed={writesAllowed}
        meetingStatus={meetingStatus}
        onLocalTerminalUtterance={terminateUtterance}
        onSpeechStatusChange={setLocalSpeechStatus}
      />
    </div>
  );
}

// ── Seat Header ──────────────────────────────────────────────────────────────

interface SeatHeaderProps {
  seatId: number;
  onBack?: () => void;
  meetingTitle?: string;
  actions?: ReactNode;
  onMaintenanceHoldStart?: () => void;
  onMaintenanceHoldEnd?: () => void;
}

function SeatHeader({
  seatId,
  onBack,
  meetingTitle,
  actions,
  onMaintenanceHoldStart,
  onMaintenanceHoldEnd,
}: SeatHeaderProps) {
  return (
    <header className="seat-focus-header">
      {onBack && (
        <button type="button" className="seat-focus-icon" aria-label="返回 / Back" onClick={onBack}>
          <ArrowLeft size={19} aria-hidden="true" />
        </button>
      )}
      <div className="seat-focus-context">
        <p>座位 {seatId} <span>/ Seat {seatId}</span></p>
        {meetingTitle && <h1>{meetingTitle}</h1>}
      </div>
      <div className="seat-focus-header-actions">
        {actions}
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
            className="seat-focus-icon touch-none select-none"
          >
            <Cpu size={16} aria-hidden="true" />
          </button>
        )}
      </div>
    </header>
  );
}

function CurrentTopicCard({ agendaState }: { agendaState: ReturnType<typeof deriveAgendaState> }) {
  const { current, progress, isFlowDone } = agendaState;
  const progressIndex = progress.current_index ?? progress.completed + progress.skipped;

  return (
    <div className="seat-focus-topic">
      <div className="seat-focus-topic-label">
        <List size={17} aria-hidden="true" />
        <DualLabel cn="当前议题" en="CURRENT TOPIC" />
      </div>
      {current ? (
        <h2>{current.title}</h2>
      ) : (
        <h2>
          <span>{isFlowDone ? "所有议题已处理" : "暂无当前议题"}</span>
          <small>{isFlowDone ? "ALL TOPICS PROCESSED" : "NO ACTIVE TOPIC"}</small>
        </h2>
      )}
      <div className="seat-focus-topic-status">
        {current && <DualLabel cn="进行中" en="ACTIVE" />}
        {progress.total > 0 && (
          <p>议程进度 / Progress: {progressIndex} / {progress.total}</p>
        )}
      </div>
    </div>
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
    case "NOT_ENROLLED":
    case "ERROR":
    case "UNAVAILABLE":
      return { cn: "验证暂不可用，请联系主持人", en: "Verification unavailable. Contact the host." };
    default:
      return { cn: "状态未知", en: "UNKNOWN" };
  }
}

function NativeIdentityPanel({ status }: { status: NativeIdentityStatus | null }) {
  const copy = status ? identityStatusCopy(status.status) : { cn: "等待人脸", en: "Waiting for face" };

  return (
    <div data-testid="native-identity-panel" className="seat-focus-identity-state" role="status">
      <DualLabel cn={copy.cn} en={copy.en} />
      {status?.status === "VERIFIED" && (
        <p className="mt-2 text-xs text-techMuted">正在确认席位 / Confirming your seat</p>
      )}
    </div>
  );
}

interface SeatOptionsProps {
  demoControlsEnabled: boolean;
  onVacate: () => void;
  writesAllowed: boolean;
  meetingStatus: "no_meeting" | "meeting_active";
  tabletVacateAvailable: boolean;
  onTabletVacate: () => void;
  tabletVacateSubmitting: boolean;
}

function SeatOptions({
  demoControlsEnabled,
  onVacate,
  writesAllowed,
  meetingStatus,
  tabletVacateAvailable,
  onTabletVacate,
  tabletVacateSubmitting,
}: SeatOptionsProps) {
  if (!tabletVacateAvailable && !demoControlsEnabled) return null;
  return (
    <details className="seat-focus-disclosure">
      <summary data-testid="seat-options" aria-label="席位选项 / Seat options">
        <MoreHorizontal size={18} aria-hidden="true" />
        <span>席位 <small>Seat</small></span>
      </summary>
      <div className="seat-focus-disclosure-panel">
        {tabletVacateAvailable && (
          <ActionButton
            variant="secondary"
            size="sm"
            touch
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
            touch
            onClick={onVacate}
            disabled={!canVacateSeat(meetingStatus, true, writesAllowed)}
          >
            模拟离座 / Vacate Seat (Demo)
          </ActionButton>
        )}
      </div>
    </details>
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
  voteStats: VoteStatistics | null;
  onRetryStats: () => void;
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
  onRetryStats,
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
      {voteStats && (
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
      )}

      {voteStatsError && (
        <div className="mb-3 bg-techAmber/10 border border-techAmber/30 rounded-lg px-3 py-2 flex items-center gap-2">
          <AlertCircle size={12} className="text-techAmber flex-shrink-0" />
          <p role="alert" className="flex-1 text-xs text-techAmber">{voteStatsError}</p>
          <ActionButton size="sm" variant="secondary" onClick={onRetryStats}>重试 / Retry</ActionButton>
        </div>
      )}

      {voteStats && (
      <p className="mb-4 text-xs text-techMuted">
        共 {voteStats.total_votes} 票 / {voteStats.total_votes} vote{voteStats.total_votes !== 1 ? "s" : ""} cast
      </p>
      )}

      {!isClosed && (
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
      )}

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
  compact?: boolean;
  meetingId: number | null;
  seatId: number;
  isSpeaker: boolean;
  isCheckedIn: boolean;
  writesAllowed: boolean;
  meetingStatus: "no_meeting" | "meeting_active";
  /** Task 127A: local cleanup callback — immediately removes live caption. */
  onLocalTerminalUtterance?: (utteranceId: string, reason: string) => void;
  onSpeechStatusChange?: (status: SpeechStatus) => void;
}

export function SpeechControl({
  compact = false,
  meetingId,
  seatId,
  isSpeaker,
  isCheckedIn,
  writesAllowed,
  meetingStatus,
  onLocalTerminalUtterance,
  onSpeechStatusChange,
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
    isSpeaker && isCheckedIn && writesAllowed && meetingStatus === "meeting_active",
    onLocalTerminalUtterance ? { onLocalTerminalUtterance } : undefined,
  );

  useEffect(() => {
    onSpeechStatusChange?.(status);
  }, [onSpeechStatusChange, status]);

  useEffect(() => () => onSpeechStatusChange?.("idle"), [onSpeechStatusChange]);

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

  const diagnostics = (
    <>
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
    </>
  );

  const languageSelector = (
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
  );

  const micActions = (
    <div className={compact ? "seat-focus-mic-actions" : "flex flex-wrap items-center gap-2"}>
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
            variant={compact ? "primary" : "secondary"}
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
  );

  if (compact) {
    if (!isSpeaker) return null;

    let voiceStatus: ReactNode;
    switch (status) {
      case "requesting_microphone":
        voiceStatus = <>正在请求麦克风权限 / Waiting for microphone access</>;
        break;
      case "connecting_speech_ws":
        voiceStatus = <>正在连接语音服务 / Connecting voice service</>;
        break;
      case "recording":
        voiceStatus = <>正在识别 / <span>Recording</span></>;
        break;
      case "stopping":
        voiceStatus = <>正在停止 / <span>Stopping...</span></>;
        break;
      case "error":
        voiceStatus = error ?? "语音识别失败 / Speech recognition failed";
        break;
      default:
        voiceStatus = !browserSupportsMic ? "麦克风不可用 / Microphone unavailable"
          : !writesAllowed ? "正在恢复连接 / Reconnecting"
          : speechStatusError ? "语音服务不可用 / Voice service unavailable"
          : !modelsReady ? <>正在准备语音服务 / <span>Loading models</span></>
          : "麦克风就绪 / Microphone ready";
    }

    return (
      <section className="seat-focus-mic" aria-label="麦克风 / Microphone" data-status={status}>
        <div className="seat-focus-mic-status" role={status === "error" ? "alert" : "status"}>
          <Mic size={19} aria-hidden="true" />
          <p>{voiceStatus}</p>
        </div>
        <div className="seat-focus-mic-controls">
          {micActions}
          <details className="seat-focus-disclosure seat-focus-mic-settings">
            <summary aria-label="麦克风设置 / Microphone settings">
              <span>语言 <small>Language</small></span>
              <ChevronDown size={14} aria-hidden="true" />
            </summary>
            <div className="seat-focus-disclosure-panel">
              {languageSelector}
              {chinesePunctuationUnavailable && (
                <p className="text-xs text-techMuted">中文标点使用基础模式 / Simplified Chinese punctuation</p>
              )}
              {englishPunctuationUnavailable && (
                <p className="text-xs text-techMuted">英文字幕暂时没有自动标点 / English captions have no automatic punctuation</p>
              )}
              {!translationReady && !modelsPreloading && (
                <p className="text-xs text-techMuted">翻译暂不可用 / Translation temporarily unavailable</p>
              )}
            </div>
          </details>
        </div>
      </section>
    );
  }

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
          仅当前发言席可识别。 / Only the current speaker seat can use speech recognition.
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
      {diagnostics}
      {languageSelector}

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

      {micActions}

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
