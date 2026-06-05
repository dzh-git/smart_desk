import { useState, useMemo } from "react";
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
  Coffee,
  Droplets,
  Leaf,
  MoreHorizontal,
  XCircle,
  Clock,
  Vote,
  CheckCircle2,
} from "lucide-react";
import { useSeatData } from "../hooks/useSeatData";
import { useClock, formatTime, formatDuration } from "./shared";
import { isDemoControlsEnabled } from "./shared";
import {
  checkinSeat,
  devOccupySeat,
  devVacateSeat,
  submitVote,
  createServiceCall,
  cancelServiceCall,
} from "../api/resources";
import type { ServiceType } from "../api/types";

// ── Props ────────────────────────────────────────────────────────────────────

interface SeatTabletProps {
  seatId: number;
  onSwitchToAdmin: () => void;
}

// ── Main Component ───────────────────────────────────────────────────────────

export function SeatTablet({ seatId, onSwitchToAdmin }: SeatTabletProps) {
  const {
    loading,
    error,
    meeting,
    seats,
    speakerSeatId,
    attendees,
    unboundAttendees,
    activeVote,
    voteStats,
    voteStatsError,
    currentServiceCall,
    translations,
    connection,
    noMeeting,
    refresh,
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

  // Get the current vote submission status for this seat's attendee
  const voteSubmission = useMemo(() => {
    if (!activeVote || !myAttendeeName) return null;
    const myId = attendees.find((a) => a.name === myAttendeeName)?.id;
    if (!myId || !voteStats) return null;

    for (const result of voteStats.results) {
      if (result.attendee_ids?.includes(myId)) {
        return { option: result.option, attendeeId: myId };
      }
    }
    // If anonymous, we can't check, but let's still allow submission
    return { option: null, attendeeId: myId };
  }, [activeVote, voteStats, myAttendeeName, attendees]);

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
    if (!selectedVoteOption || !voteSubmission?.attendeeId) return;
    setSubmittingVote(true);
    setActionError(null);
    try {
      await submitVote(
        activeVote!.id,
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

  // ── Whether writes are allowed ─────────────────────────────────────────

  const writesAllowed = wsConnected && !!meeting;

  // ── Loading State ──────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <SeatHeader
          seatId={seatId}
          connection={connection}
          onBack={onSwitchToAdmin}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4">
            <Loader2
              size={32}
              className="animate-spin text-sky-500 mx-auto"
            />
            <p className="text-sm font-medium text-slate-600">
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
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <SeatHeader
          seatId={seatId}
          connection={connection}
          onBack={onSwitchToAdmin}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4 max-w-md">
            <div className="w-14 h-14 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mx-auto">
              <AlertCircle className="text-red-500" size={24} />
            </div>
            <p className="text-sm font-semibold text-slate-800">
              Failed to load data
            </p>
            <p className="text-xs text-slate-500">{error}</p>
            <button
              onClick={refresh}
              className="inline-flex items-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors"
            >
              <RefreshCw size={14} />
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── No Meeting State ───────────────────────────────────────────────────

  if (noMeeting) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <SeatHeader
          seatId={seatId}
          connection={connection}
          onBack={onSwitchToAdmin}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4 max-w-md">
            <div className="w-16 h-16 rounded-full bg-sky-50 border-2 border-sky-200 flex items-center justify-center mx-auto">
              <Cpu className="text-sky-500" size={28} />
            </div>
            <p className="text-base font-bold text-slate-800">
              Waiting for Meeting
            </p>
            <p className="text-xs text-slate-500">
              The seat interface will activate once a meeting starts.
            </p>
            <button
              onClick={refresh}
              className="inline-flex items-center gap-2 text-xs font-medium bg-sky-100 text-sky-700 border border-sky-200 rounded-lg px-4 py-2 hover:bg-sky-200 transition-colors"
            >
              <RefreshCw size={14} />
              Refresh
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Active Meeting ─────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col relative">
      <SeatHeader
        seatId={seatId}
        connection={connection}
        onBack={onSwitchToAdmin}
        meetingTitle={meeting?.title ?? undefined}
      />

      <main className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
        {/* Meeting info bar */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-500 font-medium">
                {meeting?.title ?? "Meeting"}
              </p>
              {elapsedMs > 0 && (
                <p className="text-xs text-slate-400 mt-0.5">
                  {formatDuration(elapsedMs)} elapsed
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              {isSpeaker && (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2.5 py-1">
                  <Mic size={12} />
                  Speaking
                </span>
              )}
              <ConnectionBadge status={connection} />
            </div>
          </div>
        </div>

        {/* Action error */}
        {actionError && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-center gap-2">
            <AlertCircle size={14} className="text-red-500 flex-shrink-0" />
            <p className="text-xs text-red-700">{actionError}</p>
            <button
              onClick={() => setActionError(null)}
              className="ml-auto text-red-400 hover:text-red-600"
            >
              <XCircle size={14} />
            </button>
          </div>
        )}

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
        />

        {/* Voting Section — only for checked-in seats with active vote */}
        {isCheckedIn && activeVote && activeVote.status === "open" && (
          <SeatVoteSection
            vote={activeVote}
            voteStats={voteStats}
            voteStatsError={voteStatsError}
            currentVote={voteSubmission?.option ?? null}
            selectedOption={selectedVoteOption}
            onSelectOption={setSelectedVoteOption}
            onSubmit={handleVoteSubmit}
            submitting={submittingVote}
            writesAllowed={writesAllowed}
          />
        )}

        {/* Vote closed info */}
        {isCheckedIn && activeVote && activeVote.status === "closed" && (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-4">
            <div className="flex items-center gap-2 mb-2">
              <Vote size={16} className="text-slate-400" />
              <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
                Vote
              </p>
            </div>
            <p className="text-sm text-slate-600">{activeVote.title}</p>
            <span className="inline-flex items-center text-xs text-slate-500 bg-slate-100 rounded-full px-2 py-0.5 mt-1">
              Closed
            </span>
          </div>
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
          />
        )}

        {/* Voice Placeholder */}
        <VoicePlaceholder />

        {/* Translation history */}
        {translations.length > 0 && (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-4">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3">
              Bilingual Transcript
            </p>
            <div className="space-y-3 max-h-48 overflow-y-auto">
              {translations.map((t) => (
                <div key={t.id} className="text-sm">
                  <p className="text-slate-700">{t.source_text}</p>
                  <p className="text-xs text-slate-500 mt-0.5 border-l-2 border-slate-200 pl-2">
                    {t.translated_text}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>

      {/* Disconnected overlay */}
      {connection === "disconnected" && (
        <div className="fixed inset-0 bg-white/80 backdrop-blur-sm flex flex-col items-center justify-center z-50">
          <div className="w-14 h-14 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mb-4">
            <WifiOff className="text-red-500" size={24} />
          </div>
          <p className="text-sm font-semibold text-slate-800 mb-1">
            Connection Lost
          </p>
          <p className="text-xs text-slate-500 mb-4">
            Attempting to reconnect...
          </p>
          <button
            onClick={refresh}
            className="inline-flex items-center gap-2 text-xs font-medium text-sky-600 border border-sky-200 rounded-full px-4 py-1.5 hover:bg-sky-50 transition-colors"
          >
            <RefreshCw size={12} />
            Retry Now
          </button>
        </div>
      )}
    </div>
  );
}

// ── Seat Header ──────────────────────────────────────────────────────────────

interface SeatHeaderProps {
  seatId: number;
  connection: "connecting" | "connected" | "disconnected";
  onBack: () => void;
  meetingTitle?: string;
}

function SeatHeader({
  seatId,
  connection,
  onBack,
  meetingTitle,
}: SeatHeaderProps) {
  const now = useClock();

  return (
    <header className="bg-slate-900 text-white px-4 py-3 flex items-center justify-between shadow-lg flex-shrink-0">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs font-medium text-slate-300 hover:text-white transition-colors"
        >
          <ArrowLeft size={14} />
          Back
        </button>
        <div className="w-px h-5 bg-slate-700" />
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-sky-500 flex items-center justify-center">
            <Cpu size={14} className="text-white" />
          </div>
          <span className="text-sm font-bold text-white">Seat {seatId}</span>
        </div>
        {meetingTitle && (
          <>
            <div className="w-px h-5 bg-slate-700" />
            <p className="text-xs text-slate-400 truncate max-w-[200px]">
              {meetingTitle}
            </p>
          </>
        )}
      </div>

      <div className="flex items-center gap-2">
        <ConnectionBadge status={connection} />
        <span className="text-xs font-mono text-slate-400">
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
      <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 bg-emerald-50/10 border border-emerald-800/30 rounded-full px-2 py-0.5">
        <Wifi size={10} />
        Online
      </span>
    );
  }
  if (status === "connecting") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-500 bg-amber-50/10 border border-amber-800/30 rounded-full px-2 py-0.5">
        <Loader2 size={10} className="animate-spin" />
        Connecting
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-red-400 bg-red-50/10 border border-red-800/30 rounded-full px-2 py-0.5">
      <WifiOff size={10} />
      Offline
    </span>
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
}: SeatStatusCardProps) {
  // ── Vacant ────────────────────────────────────────────────────────────
  if (isVacant) {
    return (
      <div className="bg-white rounded-2xl border border-dashed border-slate-300 shadow-sm p-6 text-center">
        <div className="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center mx-auto mb-4">
          <User size={28} className="text-slate-400" />
        </div>
        <p className="text-base font-semibold text-slate-600 mb-1">
          Seat {seatId} — Vacant
        </p>
        <p className="text-xs text-slate-400 mb-4">
          Waiting for occupant
        </p>
        {demoControlsEnabled && (
          <button
            onClick={onOccupy}
            disabled={!writesAllowed}
            className="inline-flex items-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <User size={14} />
            Occupy Seat (Demo)
          </button>
        )}
      </div>
    );
  }

  // ── Occupied Unchecked (needs check-in) ──────────────────────────────
  if (isOccupiedUnchecked) {
    return (
      <div className="bg-white rounded-2xl border border-amber-200 shadow-sm p-5">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-12 h-12 rounded-full bg-amber-50 border-2 border-amber-200 flex items-center justify-center">
            <User size={20} className="text-amber-500" />
          </div>
          <div>
            <p className="text-sm font-bold text-slate-800">
              Seat {seatId} — Check-in Required
            </p>
            <p className="text-xs text-slate-500">
              Select an attendee to bind to this seat
            </p>
          </div>
        </div>

        {/* Attendee selection */}
        {unboundAttendees.length > 0 ? (
          <div className="mb-4">
            <p className="text-xs font-medium text-slate-600 mb-2">
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
                  className={`w-full flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors ${
                    checkinAttendeeId === a.id
                      ? "border-sky-300 bg-sky-50"
                      : "border-slate-200 bg-white hover:bg-slate-50"
                  }`}
                >
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold ${
                      checkinAttendeeId === a.id
                        ? "bg-sky-500"
                        : "bg-slate-400"
                    }`}
                  >
                    {a.name
                      .split(" ")
                      .slice(0, 2)
                      .map((n) => n[0])
                      .join("")}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-slate-800">
                      {a.name}
                    </p>
                    <p className="text-xs text-slate-500">{a.title}</p>
                  </div>
                  {checkinAttendeeId === a.id && (
                    <CheckCircle2
                      size={16}
                      className="text-sky-500 flex-shrink-0"
                    />
                  )}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-xs text-amber-600 mb-4">
            No unbound attendees available for check-in.
          </p>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={onCheckin}
            disabled={!checkinAttendeeId || !writesAllowed}
            className="inline-flex items-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <UserCheck size={14} />
            Confirm Check-in
          </button>
          {demoControlsEnabled && (
            <button
              onClick={onVacate}
              disabled={!writesAllowed}
              className="inline-flex items-center gap-2 text-xs font-medium text-slate-600 bg-slate-100 border border-slate-200 rounded-lg px-4 py-2 hover:bg-slate-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Vacate (Demo)
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Checked In ───────────────────────────────────────────────────────
  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
      <div className="flex items-center gap-3">
        <div
          className={`w-12 h-12 rounded-full flex items-center justify-center text-white text-sm font-bold ${
            isSpeaker
              ? "bg-emerald-500 ring-2 ring-emerald-300"
              : "bg-sky-600"
          }`}
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
          <p className="text-sm font-bold text-slate-800">
            {myAttendee?.name ?? `Seat ${seatId}`}
          </p>
          <p className="text-xs text-slate-500">
            {myAttendee?.title ?? "Attendee"}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {isSpeaker && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2.5 py-1">
              <Mic size={12} />
              Speaker
            </span>
          )}
          <span className="inline-flex items-center gap-1 text-xs font-medium text-sky-700 bg-sky-50 border border-sky-200 rounded-full px-2.5 py-1">
            <UserCheck size={12} />
            Checked In
          </span>
        </div>
      </div>

      {demoControlsEnabled && (
        <div className="mt-3 pt-3 border-t border-slate-100">
          <button
            onClick={onVacate}
            disabled={!writesAllowed}
            className="text-xs font-medium text-slate-500 bg-slate-100 border border-slate-200 rounded-lg px-3 py-1.5 hover:bg-slate-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Vacate Seat (Demo)
          </button>
        </div>
      )}
    </div>
  );
}

// ── Seat Vote Section ────────────────────────────────────────────────────────

interface SeatVoteSectionProps {
  vote: { id: number; title: string; options: string[]; is_anonymous: boolean };
  voteStats: {
    results: Array<{ option: string; count: number }>;
    total_votes: number;
  } | null;
  voteStatsError: string | null;
  currentVote: string | null;
  selectedOption: string | null;
  onSelectOption: (option: string | null) => void;
  onSubmit: () => void;
  submitting: boolean;
  writesAllowed: boolean;
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
}: SeatVoteSectionProps) {
  const hasVoted = currentVote != null;

  return (
    <div className="bg-white rounded-2xl border border-sky-200 shadow-sm p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Vote size={16} className="text-sky-500" />
          <p className="text-xs font-semibold uppercase tracking-widest text-sky-600">
            Active Vote
          </p>
        </div>
        <span className="text-xs font-medium text-sky-700 bg-sky-50 border border-sky-200 rounded-full px-2 py-0.5">
          {vote.is_anonymous ? "Anonymous" : "Open"}
        </span>
      </div>

      <p className="text-sm font-semibold text-slate-800 mb-3">
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
                <span className="w-16 text-slate-600 font-medium text-right">
                  {opt.option}
                </span>
                <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-sky-400 transition-all duration-500"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="w-10 text-slate-500">
                  {pct}%
                </span>
              </div>
            );
          })}
        </div>
      )}

      {voteStatsError && (
        <p className="text-xs text-amber-600 mb-3">{voteStatsError}</p>
      )}

      {/* Vote option selection */}
      <div className="space-y-1.5 mb-3">
        {vote.options.map((option) => {
          const isSelected = selectedOption === option;
          const isMyVote = currentVote === option;
          return (
            <button
              key={option}
              onClick={() => onSelectOption(isSelected ? null : option)}
              disabled={!writesAllowed}
              className={`w-full flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors ${
                isSelected
                  ? "border-sky-300 bg-sky-50"
                  : isMyVote
                    ? "border-emerald-200 bg-emerald-50"
                    : "border-slate-200 bg-white hover:bg-slate-50"
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              <div
                className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                  isSelected
                    ? "border-sky-500"
                    : isMyVote
                      ? "border-emerald-400"
                      : "border-slate-300"
                }`}
              >
                {(isSelected || isMyVote) && (
                  <div
                    className={`w-2.5 h-2.5 rounded-full ${
                      isSelected ? "bg-sky-500" : "bg-emerald-400"
                    }`}
                  />
                )}
              </div>
              <span className="text-sm font-medium text-slate-700">
                {option}
              </span>
              {isMyVote && (
                <span className="ml-auto text-xs text-emerald-600 font-medium">
                  Your vote
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between">
        <button
          onClick={onSubmit}
          disabled={!selectedOption || submitting || !writesAllowed}
          className="inline-flex items-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <CheckCircle2 size={14} />
          )}
          {hasVoted ? "Update Vote" : "Submit Vote"}
        </button>
        {hasVoted && (
          <p className="text-xs text-slate-400">
            Your current vote: <span className="font-semibold">{currentVote}</span>
          </p>
        )}
      </div>
    </div>
  );
}

// ── Seat Service Section ─────────────────────────────────────────────────────

const SERVICE_TYPES: Array<{
  type: ServiceType;
  label: string;
  icon: React.ReactNode;
  color: string;
}> = [
  {
    type: "coffee",
    label: "Coffee",
    icon: <Coffee size={16} />,
    color: "text-amber-600 bg-amber-50 border-amber-200 hover:bg-amber-100",
  },
  {
    type: "tea",
    label: "Tea",
    icon: <Leaf size={16} />,
    color: "text-green-600 bg-green-50 border-green-200 hover:bg-green-100",
  },
  {
    type: "water",
    label: "Water",
    icon: <Droplets size={16} />,
    color: "text-sky-600 bg-sky-50 border-sky-200 hover:bg-sky-100",
  },
  {
    type: "other",
    label: "Other",
    icon: <MoreHorizontal size={16} />,
    color: "text-slate-600 bg-slate-50 border-slate-200 hover:bg-slate-100",
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
}

function SeatServiceSection({
  currentCall,
  onRequest,
  onCancel,
  creating,
  cancelling,
  writesAllowed,
}: SeatServiceSectionProps) {
  const hasPending = currentCall?.status === "pending";

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
      <div className="flex items-center gap-2 mb-3">
        <Coffee size={16} className="text-slate-500" />
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          Service Request
        </p>
      </div>

      {hasPending ? (
        <div className="space-y-3">
          <div className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5">
            <Clock size={16} className="text-amber-500" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-slate-800">
                {SERVICE_TYPES.find(
                  (s) => s.type === currentCall.service_type,
                )?.label ?? currentCall.service_type}{" "}
                — Pending
              </p>
              <p className="text-xs text-slate-500">
                Your request has been sent
              </p>
            </div>
            <button
              onClick={onCancel}
              disabled={cancelling || !writesAllowed}
              className="inline-flex items-center gap-1 text-xs font-medium text-rose-600 bg-white border border-rose-200 rounded-lg px-3 py-1.5 hover:bg-rose-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {cancelling ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <XCircle size={12} />
              )}
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="text-xs text-slate-500 mb-3">
            Request a service:
          </p>
          <div className="grid grid-cols-2 gap-2">
            {SERVICE_TYPES.map((svc) => (
              <button
                key={svc.type}
                onClick={() => onRequest(svc.type)}
                disabled={creating || !writesAllowed}
                className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-sm font-medium transition-colors ${svc.color} disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {svc.icon}
                {svc.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Voice Placeholder ─────────────────────────────────────────────────────────

function VoicePlaceholder() {
  return (
    <div className="bg-white rounded-2xl border border-dashed border-slate-300 shadow-sm p-5">
      <div className="flex items-center gap-2 mb-2">
        <Mic size={16} className="text-slate-400" />
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">
          Voice Recognition
        </p>
      </div>
      <p className="text-xs text-slate-400 italic">
        语音识别接口预留 / Speech recognition interface reserved
      </p>
    </div>
  );
}
