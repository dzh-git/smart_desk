import { useState, useMemo, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Cpu,
  ArrowLeft,
  Wifi,
  WifiOff,
  Loader2,
  AlertCircle,
  RefreshCw,
  User,
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
import { TranscriptPanel } from "./TranscriptPanel";
import {
  checkinSeat,
  devOccupySeat,
  devVacateSeat,
  submitVote,
  createServiceCall,
  cancelServiceCall,
  fetchSpeechStatus,
} from "../api/resources";
import type { ServiceType, SpeechModelStatus, VoteStatistics } from "../api/types";
import {
  deriveSeatMeetingStatus,
  canCheckIn,
  canOccupySeat,
  canVacateSeat,
  canSubmitVote,
  canSelectVoteOption,
  canCallService,
  canCancelService,
  canStartSpeech,
} from "../utils/uiState";
import { deriveAgendaState } from "../utils/agendaState";

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
    unboundAttendees,
    agenda,
    activeVote,
    voteStats,
    voteResults,
    voteStatsError,
    currentServiceCall,
    translations,
    interimMap,
    pendingFinalMap,
    connection,
    noMeeting,
    refresh,
    terminateUtterance,
  } = useSeatData(seatId);

  // Local UI state
  const [checkinAttendeeId, setCheckinAttendeeId] = useState<number | null>(
    null,
  );
  const [selectedVoteOption, setSelectedVoteOption] = useState<string | null>(
    null,
  );
  const [submittingVote, setSubmittingVote] = useState(false);
  const [creatingService, setCreatingService] = useState(false);
  const [cancellingService, setCancellingService] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Derived state
  const mySeat = seats.find((s) => s.seatId === seatId) ?? null;
  const isVacant = mySeat?.isVacant ?? true;
  const isCheckedIn = mySeat?.isCheckedIn ?? false;
  const isSpeaker = speakerSeatId === seatId;
  const wsConnected = connection === "connected";
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
  const isOccupiedUnchecked =
    !isVacant && !isCheckedIn;

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

  async function handleCheckin() {
    if (!checkinAttendeeId) return;
    setActionError(null);
    try {
      await checkinSeat(seatId, checkinAttendeeId);
      setCheckinAttendeeId(null);
      refresh();
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Check-in failed",
      );
    }
  }

  async function handleOccupy() {
    setActionError(null);
    try {
      await devOccupySeat(seatId);
      refresh();
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Occupy failed",
      );
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
  const writesAllowed = wsConnected && !!meeting && meeting?.status === "active";

  // ── Loading State ──────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen bg-techBg flex flex-col">
        <SeatHeader
          seatId={seatId}
          connection={connection}
          onBack={onSwitchToAdmin}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4">
            <Loader2
              size={32}
              className="animate-spin text-techCyan mx-auto"
            />
            <p className="text-sm font-medium text-techMuted">
              Loading seat data...
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Error State ────────────────────────────────────────────────────────

  if (error) {
    return (
      <div className="min-h-screen bg-techBg flex flex-col">
        <SeatHeader
          seatId={seatId}
          connection={connection}
          onBack={onSwitchToAdmin}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4 max-w-md">
            <div className="w-14 h-14 rounded-full bg-techRose/10 border-2 border-techRose/30 flex items-center justify-center mx-auto">
              <AlertCircle className="text-techRose" size={24} />
            </div>
            <p className="text-sm font-semibold text-techText">
              Failed to load data
            </p>
            <p className="text-xs text-techMuted">{error}</p>
            <ActionButton
              variant="primary"
              size="md"
              icon={<RefreshCw size={14} />}
              onClick={refresh}
            >
              Retry
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
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4 max-w-md">
            <div className="w-16 h-16 rounded-full bg-techCardSoft border-2 border-techBorder flex items-center justify-center mx-auto">
              <Cpu className="text-techCyan" size={28} />
            </div>
            <p className="text-base font-bold text-techText">
              Waiting for Meeting
            </p>
            <p className="text-xs text-techMuted">
              The seat interface will activate once a meeting starts.
            </p>
            <ActionButton
              variant="secondary"
              size="md"
              icon={<RefreshCw size={14} />}
              onClick={refresh}
            >
              Refresh
            </ActionButton>
          </div>
        </div>
      </div>
    );
  }

  // ── Active Meeting ─────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-techBg bg-tech-radial flex flex-col relative">
      <SeatHeader
        seatId={seatId}
        connection={connection}
        onBack={onSwitchToAdmin}
        meetingTitle={meeting?.title ?? undefined}
        elapsedMs={elapsedMs}
      />

      <main className="flex-1 overflow-y-auto p-4 space-y-4 max-w-[900px] mx-auto w-full">
        {/* Action error */}
        {actionError && (
          <div className="bg-techRose/10 border border-techRose/30 rounded-lg px-4 py-3 flex items-center gap-2">
            <AlertCircle size={14} className="text-techRose flex-shrink-0" />
            <p className="text-xs text-techRose flex-1">{actionError}</p>
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
          isVacant={isVacant}
          isOccupiedUnchecked={isOccupiedUnchecked}
          isSpeaker={isSpeaker}
          myAttendee={myAttendeeName ? { name: myAttendeeName, title: myAttendeeTitle } : null}
          unboundAttendees={unboundAttendees}
          checkinAttendeeId={checkinAttendeeId}
          onSelectAttendee={setCheckinAttendeeId}
          onCheckin={handleCheckin}
          demoControlsEnabled={isDemoControlsEnabled()}
          onOccupy={handleOccupy}
          onVacate={handleVacate}
          writesAllowed={writesAllowed}
          meetingStatus={meetingStatus}
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
          interims={Object.values(interimMap)}
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
            Connection Lost
          </p>
          <p className="text-xs text-techMuted mb-4">
            Attempting to reconnect...
          </p>
          <ActionButton
            variant="secondary"
            size="sm"
            icon={<RefreshCw size={12} />}
            onClick={refresh}
          >
            Retry Now
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
}

function SeatHeader({
  seatId,
  connection,
  onBack,
  meetingTitle,
  elapsedMs,
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
              Back
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

interface SeatStatusCardProps {
  seatId: number;
  isVacant: boolean;
  isOccupiedUnchecked: boolean;
  isSpeaker: boolean;
  myAttendee: { name: string | null; title: string | null } | null;
  unboundAttendees: { id: number; name: string; title: string }[];
  checkinAttendeeId: number | null;
  onSelectAttendee: (id: number | null) => void;
  onCheckin: () => void;
  demoControlsEnabled: boolean;
  onOccupy: () => void;
  onVacate: () => void;
  writesAllowed: boolean;
  meetingStatus: "no_meeting" | "meeting_active";
}

function SeatStatusCard({
  seatId,
  isVacant,
  isOccupiedUnchecked,
  isSpeaker,
  myAttendee,
  unboundAttendees,
  checkinAttendeeId,
  onSelectAttendee,
  onCheckin,
  demoControlsEnabled,
  onOccupy,
  onVacate,
  writesAllowed,
  meetingStatus,
}: SeatStatusCardProps) {
  // ── Vacant ────────────────────────────────────────────────────────────
  if (isVacant) {
    return (
      <div className="bg-techCard border border-dashed border-techBorder rounded-lg p-6 text-center shadow-card-glow">
        <div className="w-16 h-16 rounded-full bg-techCardSoft flex items-center justify-center mx-auto mb-4">
          <User size={28} className="text-techMuted" />
        </div>
        <div className="mb-1">
          <DualLabel
            cn={`座位 ${seatId} · 空座`}
            en="Vacant"
            className="justify-center"
            cnClassName="text-base font-semibold text-techMuted"
            enClassName="text-xs"
          />
        </div>
        <p className="text-xs text-techMuted/70 mb-4">
          Waiting for occupant
        </p>
        {demoControlsEnabled && (
          <ActionButton
            variant="primary"
            size="lg"
            touch
            icon={<User size={16} />}
            onClick={onOccupy}
            disabled={!canOccupySeat(meetingStatus, isVacant, writesAllowed)}
          >
            Occupy Seat (Demo)
          </ActionButton>
        )}
      </div>
    );
  }

  // ── Occupied Unchecked (needs check-in) ──────────────────────────────
  if (isOccupiedUnchecked) {
    return (
      <PanelCard variant="warning" className="shadow-card-glow">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-12 h-12 rounded-full bg-techAmber/10 border-2 border-techAmber/30 flex items-center justify-center">
            <User size={20} className="text-techAmber" />
          </div>
          <div>
            <DualLabel
              cn={`座位 ${seatId} · 待签到`}
              en="Check-in Required"
              cnClassName="text-sm font-bold text-techText"
              enClassName="text-xs"
            />
            <p className="text-xs text-techMuted mt-0.5">
              Select an attendee to bind to this seat
            </p>
          </div>
        </div>

        {/* Attendee selection */}
        {unboundAttendees.length > 0 ? (
          <div className="mb-4">
            <p className="text-xs font-medium text-techMuted mb-2">
              Select attendee:
            </p>
            <div className="space-y-1.5">
              {unboundAttendees.map((a) => (
                <button
                  key={a.id}
                  onClick={() =>
                    onSelectAttendee(
                      checkinAttendeeId === a.id ? null : a.id,
                    )
                  }
                  className={cx(
                    "w-full flex items-center gap-3 rounded-lg border px-4 py-3 min-h-[48px] text-left transition-colors",
                    checkinAttendeeId === a.id
                      ? "border-techCyan bg-techCyan/10"
                      : "border-techBorder bg-techCard hover:bg-techCardSoft",
                  )}
                >
                  <div
                    className={cx(
                      "w-8 h-8 rounded-full flex items-center justify-center text-techBg text-xs font-bold",
                      checkinAttendeeId === a.id
                        ? "bg-techCyan"
                        : "bg-techMuted",
                    )}
                  >
                    {a.name
                      .split(" ")
                      .slice(0, 2)
                      .map((n) => n[0])
                      .join("")}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-techText">
                      {a.name}
                    </p>
                    <p className="text-xs text-techMuted">{a.title}</p>
                  </div>
                  {checkinAttendeeId === a.id && (
                    <CheckCircle2
                      size={16}
                      className="text-techCyan flex-shrink-0"
                    />
                  )}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-xs text-techAmber mb-4">
            No unbound attendees available for check-in.
          </p>
        )}

        <div className="flex items-center gap-2">
          <ActionButton
            variant="primary"
            size="md"
            touch
            icon={<UserCheck size={14} />}
            onClick={onCheckin}
            disabled={!canCheckIn(meetingStatus, isOccupiedUnchecked, !!checkinAttendeeId, writesAllowed)}
          >
            Confirm Check-in
          </ActionButton>
          {demoControlsEnabled && (
            <ActionButton
              variant="secondary"
              size="md"
              touch
              onClick={onVacate}
              disabled={!canVacateSeat(meetingStatus, !isVacant, writesAllowed)}
            >
              Vacate (Demo)
            </ActionButton>
          )}
        </div>
      </PanelCard>
    );
  }

  // ── Checked In ───────────────────────────────────────────────────────
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
            {myAttendee?.name ?? `Seat ${seatId}`}
          </p>
          <p className="text-sm text-techMuted">
            {myAttendee?.title ?? "Attendee"}
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

      {demoControlsEnabled && (
        <div className="mt-4 pt-4 border-t border-techBorder">
          <ActionButton
            variant="secondary"
            size="sm"
            onClick={onVacate}
            disabled={!canVacateSeat(meetingStatus, !isVacant, writesAllowed)}
          >
            Vacate Seat (Demo)
          </ActionButton>
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
            {hasVoted ? "Update Vote" : "Submit Vote"}
          </ActionButton>
        )}
        {hasVoted && (
          <p className="text-xs text-techMuted">
            Your choice: <span className="font-semibold text-techText">{currentVote}</span>
          </p>
        )}
        {isClosed && !hasVoted && (
          <p className="text-xs text-techMuted">
            Your choice is unavailable for this result.
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
              — <span className="text-techAmber">Pending</span>
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
            Cancel
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
  onLocalTerminalUtterance?: (utteranceId: string) => void;
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
  const { status, error, start, stop, cancel } = useSpeechStream(
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
  const punctuationFallback = speechStatus?.punctuation_fallback ?? true;
  const translationReady = speechStatus?.translation_model === "loaded";
  const translationError = speechStatus?.translation_last_error ?? null;

  const browserSupportsMic =
    typeof navigator !== "undefined" &&
    navigator.mediaDevices?.getUserMedia != null;

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
          Only speaker seat can stream audio
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
            Speech models loading...
          </p>
        </div>
      )}

      {/* Punctuation fallback hint (non-blocking) */}
      {punctuationFallback && status !== "recording" && status !== "error" && status !== "requesting_microphone" && status !== "connecting_speech_ws" && (
        <div className="mb-3 bg-techAmber/10 border border-techAmber/30 rounded-lg px-3 py-1.5 flex items-start gap-2">
          <AlertCircle size={12} className="text-techAmber flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-techAmber">
            Punctuation model unavailable — basic fallback active
          </p>
        </div>
      )}

      {!translationReady && !modelsPreloading && status === "idle" && (
        <div className="mb-3 bg-techAmber/10 border border-techAmber/30 rounded-lg px-3 py-1.5 flex items-start gap-2">
          <AlertCircle size={12} className="text-techAmber flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-techAmber">
            {translationError
              ? `英文翻译模型不可用：${translationError}`
              : "英文翻译模型尚未就绪"}
          </p>
        </div>
      )}

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
              Dismiss
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
            — Click Start to begin speaking
          </p>
        )}
        {status === "idle" && !modelsReady && (
          <p className="text-techAmber">
            Waiting for speech models...
          </p>
        )}
        {status === "requesting_microphone" && (
          <p className="text-techAmber">
            Requesting microphone access...
          </p>
        )}
        {status === "connecting_speech_ws" && (
          <p className="text-techAmber">
            Connecting to speech service...
          </p>
        )}
        {status === "recording" && (
          <p className="text-techGreen font-medium">
            Streaming audio...
          </p>
        )}
        {status === "stopping" && (
          <p className="text-techMuted">Stopping...</p>
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
          Speech recognition models are being loaded. Start will be available once ready.
        </p>
      )}

      {/* Mic not supported warning */}
      {!browserSupportsMic && (
        <p className="mt-2 text-xs text-techAmber">
          Microphone not supported in this browser
        </p>
      )}
    </PanelCard>
  );
}
