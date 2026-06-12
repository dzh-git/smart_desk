import { useState, useCallback, useEffect, useRef } from "react";
import {
  Loader2,
  AlertCircle,
  Cpu,
  RefreshCw,
  Vote,
  XCircle,
  Play,
  Square,
  Plus,
  Trash2,
  Mic,
  MicOff,
} from "lucide-react";
import { useAdminData } from "../hooks/useAdminData";

import { AdminHeader } from "./AdminHeader";
import { ConferenceTable } from "./ConferenceTable";
import { AgendaPanel } from "./AgendaPanel";
import { VotePanel } from "./VotePanel";
import { ServicePanel } from "./ServicePanel";
import { TranscriptPanel } from "./TranscriptPanel";
import { MeetingResultPanel } from "./MeetingResultPanel";
import { SectionCard } from "./shared";
import { formatDuration, isDemoControlsEnabled } from "./shared";
import {
  createVote,
  closeVote,
  resolveServiceCall,
  createMeeting,
  startMeeting,
  endMeeting,
  setSpeakerSeat,
  clearSpeakerSeat,
  createAttendee,
  deleteAttendee,
  createAgenda,
  deleteAgenda,
  triggerSpeechPreload,
} from "../api/resources";
import type { Meeting } from "../api/types";
import {
  deriveMeetingLifecycleStatus,
  deriveAdminVoteState,
  canCreateMeeting,
  canStartMeeting,
  canEndMeeting,
  canUsePhaseSelector,
  canCreateVote,
  canCloseVote,
  canControlSpeaker,
  canManageAttendees,
  canManageAgenda,
  canResolveServiceCall,
} from "../utils/uiState";

interface AdminDashboardProps {
  onSwitchToSeat: (seatId: number) => void;
}

export function AdminDashboard({ onSwitchToSeat }: AdminDashboardProps) {
  const {
    loading,
    error,
    meeting,
    seats,
    speakerSeatId,
    attendees,
    agenda,
    activeVote,
    voteResults,
    hasActiveVote,
    voteStatsError,
    serviceCalls,
    translations,
    interimMap,
    connection,
    noMeeting,
    isEndedMeeting,
    refresh,
    clearEndedMeeting,
  } = useAdminData();

  const [activeSeatId, setActiveSeatId] = useState<number | undefined>();
  const [previewSeat, setPreviewSeat] = useState(1);

  // ── Admin action state ─────────────────────────────────────────────────
  const [createVoteTitle, setCreateVoteTitle] = useState("");
  const [createVoteOptions, setCreateVoteOptions] = useState(["", ""]);
  const [createVoteAnonymous, setCreateVoteAnonymous] = useState(false);
  const [creatingVote, setCreatingVote] = useState(false);
  const [closingVote, setClosingVote] = useState(false);
  const [adminActionError, setAdminActionError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<number | null>(null);
  const [meetingTitle, setMeetingTitle] = useState("");
  const [meetingDescription, setMeetingDescription] = useState("");
  const [pendingMeeting, setPendingMeeting] = useState<Meeting | null>(null);
  const [meetingActionBusy, setMeetingActionBusy] = useState(false);
  const [speakerBusy, setSpeakerBusy] = useState(false);
  const [attendeeName, setAttendeeName] = useState("");
  const [attendeeTitle, setAttendeeTitle] = useState("");
  const [attendeeBusy, setAttendeeBusy] = useState(false);
  const [agendaTitle, setAgendaTitle] = useState("");
  const [agendaBusy, setAgendaBusy] = useState(false);

  // ── Speech preload state ──────────────────────────────────────────────────
  const [preloadingModel, setPreloadingModel] = useState(false);
  const [preloadResult, setPreloadResult] = useState<"idle" | "success" | "error">("idle");

  // ── Derived meeting lifecycle & vote state (Task 4) ─────────────────────
  const meetingStatus = deriveMeetingLifecycleStatus(meeting, pendingMeeting, isEndedMeeting);
  const voteState = deriveAdminVoteState(hasActiveVote, voteResults);

  // ── UI Phase (local host-only state) ───────────────────────────────────
  const [uiPhase, setUiPhase] = useState<"general" | "agenda_discussion">("general");
  const prevMeetingIdRef = useRef<number | null>(null);

  // Reset uiPhase to "general" when the active meeting changes to a new one
  useEffect(() => {
    if (meeting?.id && meeting.id !== prevMeetingIdRef.current && prevMeetingIdRef.current !== null) {
      setUiPhase("general");
    }
    if (meeting?.id) {
      prevMeetingIdRef.current = meeting.id;
    }
  }, [meeting?.id]);

  // ── Admin action handlers ──────────────────────────────────────────────

  const handleCreateVote = useCallback(async () => {
    if (!meeting?.id) return;
    const trimmedTitle = createVoteTitle.trim();
    if (!trimmedTitle) {
      setAdminActionError("Vote title is required");
      return;
    }
    const validOptions = createVoteOptions
      .map((o) => o.trim())
      .filter((o) => o.length > 0);
    if (validOptions.length < 2) {
      setAdminActionError("At least 2 non-empty options are required");
      return;
    }
    setCreatingVote(true);
    setAdminActionError(null);
    try {
      await createVote(meeting.id, trimmedTitle, validOptions, createVoteAnonymous);
      setCreateVoteTitle("");
      setCreateVoteOptions(["", ""]);
      setCreateVoteAnonymous(false);
      refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create vote";
      setAdminActionError(msg);
    } finally {
      setCreatingVote(false);
    }
  }, [meeting?.id, createVoteTitle, createVoteOptions, createVoteAnonymous, refresh]);

  const handleCloseVote = useCallback(async (voteId: number) => {
    setClosingVote(true);
    setAdminActionError(null);
    try {
      await closeVote(voteId);
      refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to close vote";
      setAdminActionError(msg);
    } finally {
      setClosingVote(false);
    }
  }, [refresh]);

  const handleResolveCall = useCallback(async (callId: number) => {
    setResolvingId(callId);
    setAdminActionError(null);
    try {
      await resolveServiceCall(callId);
      refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to resolve service call";
      setAdminActionError(msg);
    } finally {
      setResolvingId(null);
    }
  }, [refresh]);

  const handleCreateMeeting = useCallback(async () => {
    const title = meetingTitle.trim();
    if (!title) {
      setAdminActionError("Meeting title is required");
      return;
    }
    setMeetingActionBusy(true);
    setAdminActionError(null);
    try {
      const created = await createMeeting(title, meetingDescription);
      setPendingMeeting(created);
      setMeetingTitle("");
      setMeetingDescription("");
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to create meeting");
    } finally {
      setMeetingActionBusy(false);
    }
  }, [meetingTitle, meetingDescription]);

  const handleStartPendingMeeting = useCallback(async () => {
    if (!pendingMeeting) return;
    setMeetingActionBusy(true);
    setAdminActionError(null);
    try {
      await startMeeting(pendingMeeting.id);
      setPendingMeeting(null);
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to start meeting");
    } finally {
      setMeetingActionBusy(false);
    }
  }, [pendingMeeting, refresh]);

  const handleEndMeeting = useCallback(async () => {
    if (!meeting) return;
    const confirmed = window.confirm("End this meeting? Seats will reset and the open vote will close.");
    if (!confirmed) return;
    setMeetingActionBusy(true);
    setAdminActionError(null);
    try {
      await endMeeting(meeting.id);
      // Save ended meeting data so the hook can restore it when fetchActiveMeeting returns null
      try {
        sessionStorage.setItem('endedMeetingId', String(meeting.id));
        sessionStorage.setItem('endedMeetingTitle', meeting.title);
      } catch { /* sessionStorage may throw */ }
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to end meeting");
    } finally {
      setMeetingActionBusy(false);
    }
  }, [meeting, refresh]);

  const handleSetSpeaker = useCallback(async (seatId: number) => {
    setSpeakerBusy(true);
    setAdminActionError(null);
    try {
      await setSpeakerSeat(seatId);
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to set speaker seat");
    } finally {
      setSpeakerBusy(false);
    }
  }, [refresh]);

  const handleClearSpeaker = useCallback(async () => {
    setSpeakerBusy(true);
    setAdminActionError(null);
    try {
      await clearSpeakerSeat();
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to clear speaker seat");
    } finally {
      setSpeakerBusy(false);
    }
  }, [refresh]);

  const handleCreateAttendee = useCallback(async () => {
    if (!meeting) return;
    const name = attendeeName.trim();
    if (!name) {
      setAdminActionError("Attendee name is required");
      return;
    }
    setAttendeeBusy(true);
    setAdminActionError(null);
    try {
      await createAttendee(meeting.id, name, attendeeTitle);
      setAttendeeName("");
      setAttendeeTitle("");
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to create attendee");
    } finally {
      setAttendeeBusy(false);
    }
  }, [meeting, attendeeName, attendeeTitle, refresh]);

  const handleDeleteAttendee = useCallback(async (attendeeId: number) => {
    if (!meeting) return;
    setAttendeeBusy(true);
    setAdminActionError(null);
    try {
      await deleteAttendee(meeting.id, attendeeId);
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to delete attendee");
    } finally {
      setAttendeeBusy(false);
    }
  }, [meeting, refresh]);

  const handleCreateAgenda = useCallback(async () => {
    if (!meeting) return;
    const title = agendaTitle.trim();
    if (!title) {
      setAdminActionError("Agenda title is required");
      return;
    }
    setAgendaBusy(true);
    setAdminActionError(null);
    try {
      await createAgenda(meeting.id, title, agenda.length + 1);
      setAgendaTitle("");
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to create agenda");
    } finally {
      setAgendaBusy(false);
    }
  }, [meeting, agenda.length, agendaTitle, refresh]);

  const handleDeleteAgenda = useCallback(async (agendaId: number) => {
    if (!meeting) return;
    setAgendaBusy(true);
    setAdminActionError(null);
    try {
      await deleteAgenda(meeting.id, agendaId);
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to delete agenda");
    } finally {
      setAgendaBusy(false);
    }
  }, [meeting, refresh]);

  async function handlePreloadSpeechModel() {
    setPreloadingModel(true);
    setPreloadResult("idle");
    setAdminActionError(null);
    try {
      await triggerSpeechPreload();
      setPreloadResult("success");
    } catch (err: unknown) {
      setPreloadResult("error");
      setAdminActionError(
        err instanceof Error ? err.message : "Failed to preload speech model",
      );
    } finally {
      setPreloadingModel(false);
      // Auto-reset feedback after 3 seconds
      setTimeout(() => setPreloadResult("idle"), 3000);
    }
  }

  function handleSeatClick(seatId: number) {
    setActiveSeatId((prev) => (prev === seatId ? undefined : seatId));
  }

  // Build seat → name map for service calls and transcript
  const seatNameMap: Record<number, string> = {};
  for (const a of attendees) {
    if (a.seat_id != null) {
      seatNameMap[a.seat_id] = a.name;
    }
  }

  // Metric card data
  const checkedIn = attendees.filter((a) => a.checked_in).length;
  const speakerAttendee =
    speakerSeatId != null ? seatNameMap[speakerSeatId] ?? null : null;
  const pendingRequests = serviceCalls.filter(
    (c) => c.status === "pending",
  ).length;
  const selectedSeat = activeSeatId != null
    ? seats.find((s) => s.seatId === activeSeatId)
    : undefined;
  const elapsedMs =
    meeting?.started_at != null
      ? Date.now() - new Date(meeting.started_at).getTime()
      : 0;

  // ── Loading State ──────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4">
            <Loader2 size={32} className="animate-spin text-sky-500 mx-auto" />
            <p className="text-sm font-medium text-slate-600">
              Loading meeting data...
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
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
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
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="w-full max-w-lg space-y-4">
            <div className="w-16 h-16 rounded-full bg-sky-50 border-2 border-sky-200 flex items-center justify-center mx-auto">
              <Cpu className="text-sky-500" size={28} />
            </div>
            <div className="text-center">
              <p className="text-base font-bold text-slate-800">
                No Active Meeting
              </p>
              <p className="text-xs text-slate-500">
                Create a pending meeting, then start it when the room is ready.
              </p>
            </div>

            {adminActionError && (
              <div className="bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 flex items-center gap-2">
                <AlertCircle size={14} className="text-rose-500 flex-shrink-0" />
                <p className="text-xs text-rose-700">{adminActionError}</p>
                <button
                  onClick={() => setAdminActionError(null)}
                  className="ml-auto text-rose-400 hover:text-rose-600"
                >
                  <XCircle size={14} />
                </button>
              </div>
            )}

            <SectionCard title="Create Meeting">
              <div className="space-y-3">
                <input
                  type="text"
                  value={meetingTitle}
                  onChange={(e) => setMeetingTitle(e.target.value)}
                  placeholder="Meeting title"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-400 focus:border-transparent"
                />
                <textarea
                  value={meetingDescription}
                  onChange={(e) => setMeetingDescription(e.target.value)}
                  placeholder="Optional description"
                  rows={3}
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-400 focus:border-transparent"
                />
                <button
                  onClick={handleCreateMeeting}
                  disabled={!canCreateMeeting(meetingStatus, !meetingTitle.trim(), meetingActionBusy)}
                  className="w-full inline-flex items-center justify-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {meetingActionBusy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={14} />}
                  Create Pending Meeting
                </button>
              </div>
            </SectionCard>

            {pendingMeeting && (
              <SectionCard
                title="Pending Meeting"
                headerRight={
                  <span className="text-xs font-medium text-amber-600">
                    Ready to start
                  </span>
                }
              >
                <div className="space-y-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-800">
                      {pendingMeeting.title}
                    </p>
                    {pendingMeeting.description && (
                      <p className="text-xs text-slate-500 mt-1">
                        {pendingMeeting.description}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={handleStartPendingMeeting}
                    disabled={!canStartMeeting(meetingStatus, !!pendingMeeting, meetingActionBusy)}
                    className="w-full inline-flex items-center justify-center gap-2 text-xs font-medium bg-emerald-600 text-white rounded-lg px-4 py-2 hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {meetingActionBusy ? <Loader2 size={12} className="animate-spin" /> : <Play size={14} />}
                    Start Meeting
                  </button>
                </div>
              </SectionCard>
            )}

            <div className="text-center">
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
      </div>
    );
  }

  // ── Active Meeting ─────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col relative">
      <AdminHeader
        title={meeting?.title ?? ""}
        meetingStatus={meeting?.status ?? "pending"}
        connection={connection}
        onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
        previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
      />

      {/* Seat preview selector — only visible in demo mode */}
      {isDemoControlsEnabled() && (
        <div className="bg-slate-900 border-t border-slate-800 px-4 sm:px-6 py-2 flex flex-wrap items-center gap-3">
          <span className="shrink-0 text-xs text-slate-500 font-medium">
            Preview seat:
          </span>
          <div className="flex flex-wrap gap-1.5">
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <button
                key={n}
                onClick={() => setPreviewSeat(n)}
                className={`w-7 h-7 rounded-md text-xs font-semibold transition-colors ${
                  previewSeat === n
                    ? "bg-sky-500 text-white"
                    : "bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-300"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          <button
            onClick={() => onSwitchToSeat(previewSeat)}
            className="w-full sm:w-auto sm:ml-auto text-xs font-medium text-sky-400 border border-sky-800 hover:bg-sky-900/50 transition-colors rounded-lg px-3 py-1"
          >
            Open Seat Tablet View
          </button>
        </div>
      )}

      <main className="flex-1 p-4 sm:p-6 overflow-auto">
        {/* Summary row / Ended meeting banner */}
        {isEndedMeeting ? (
          <div className="mb-6">
            <div className="rounded-xl border-2 border-slate-300 bg-slate-100 p-4 text-center">
              <p className="text-lg font-bold text-slate-600">Meeting Ended</p>
              <p className="text-sm text-slate-500 mt-1">{meeting?.title}</p>
            </div>
          </div>
        ) : (
          <div className="mb-6 space-y-3">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <MetricCard
                label="Elapsed"
                value={elapsedMs > 0 ? formatDuration(elapsedMs) : "—"}
                sub="Meeting time"
                accent="text-sky-700"
              />
              <MetricCard
                label="Attendees"
                value={`${checkedIn}/10`}
                sub="Checked in"
                accent={
                  checkedIn >= 9 ? "text-emerald-700" : "text-amber-600"
                }
              />
              <MetricCard
                label="Speaker"
                value={speakerAttendee?.split(" ")[0] ?? "—"}
                sub={speakerAttendee ?? "No active speaker"}
                accent="text-emerald-700"
              />
              <MetricCard
                label="Requests"
                value={pendingRequests}
                sub="Pending service"
                accent={
                  pendingRequests > 0 ? "text-rose-600" : "text-slate-600"
                }
              />
            </div>

            {/* Phase selector — only in active meeting */}
            {canUsePhaseSelector(meetingStatus) && (
            <div className="flex flex-wrap items-center gap-3 bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3">
              <span className="text-xs font-semibold text-slate-600">
                Current Phase:
              </span>
              <div className="flex rounded-lg border border-slate-200 overflow-hidden">
                <button
                  onClick={() => setUiPhase("general")}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                    uiPhase === "general"
                      ? "bg-sky-600 text-white"
                      : "bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  General
                </button>
                <button
                  onClick={() => setUiPhase("agenda_discussion")}
                  className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                    uiPhase === "agenda_discussion"
                      ? "bg-sky-600 text-white"
                      : "bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  Agenda Discussion
                </button>
              </div>
              {uiPhase === "agenda_discussion" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-[10px] font-semibold text-amber-700">
                  Agenda Discussion
                </span>
              )}
            </div>
          )}

          {/* Speech Model Preload — only in active meeting */}
          {canUsePhaseSelector(meetingStatus) && (
            <div className="flex flex-wrap items-center gap-3 bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3">
              <span className="text-xs font-semibold text-slate-600">
                Speech Model:
              </span>
              <button
                onClick={handlePreloadSpeechModel}
                disabled={preloadingModel}
                className="inline-flex items-center gap-2 text-xs font-medium bg-amber-600 text-white rounded-lg px-4 py-2 hover:bg-amber-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {preloadingModel ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <Cpu size={13} />
                )}
                {preloadingModel ? "Preloading..." : "Preload Speech Model"}
              </button>
              {preloadResult === "success" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                  Preload triggered
                </span>
              )}
              {preloadResult === "error" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2.5 py-0.5 text-[10px] font-semibold text-rose-700">
                  Preload failed
                </span>
              )}
            </div>
          )}
          </div>
        )}

        {isEndedMeeting ? (
          <SectionCard
            title="Meeting Ended"
            headerRight={
              <span className="text-xs text-slate-400">
                ID {meeting?.id}
              </span>
            }
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm text-slate-600">
                  This meeting has ended. Results are shown below.
                </p>
              </div>
              <button
                onClick={clearEndedMeeting}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-sky-200 bg-white px-3 py-2 text-xs font-medium text-sky-600 transition-colors hover:bg-sky-50"
              >
                <Plus size={13} />
                New Meeting
              </button>
            </div>
          </SectionCard>
        ) : (
          <SectionCard
            title="Meeting Control"
            headerRight={
              <span className="text-xs text-slate-400">
                ID {meeting?.id}
              </span>
            }
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-800">
                  Active meeting controls
                </p>
                <p className="text-xs text-slate-500">
                  Status: {meeting?.status}
                </p>
              </div>
              <button
                onClick={handleEndMeeting}
                disabled={!canEndMeeting(meetingStatus, meetingActionBusy)}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-medium text-rose-600 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {meetingActionBusy ? <Loader2 size={12} className="animate-spin" /> : <Square size={13} />}
                End Meeting
              </button>
            </div>
          </SectionCard>
        )}

        {/* Main grid */}
        <div className="grid grid-cols-12 gap-6">
          {/* Conference table — wide (hidden for ended meetings) */}
          {!isEndedMeeting && (
            <div className="col-span-12 xl:col-span-8">
              <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
                <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-5">
                  Conference Room — Seat Overview
                </h3>
                <ConferenceTable
                  seats={seats}
                  currentSpeaker={speakerSeatId}
                  activeSeat={activeSeatId}
                  onSeatClick={handleSeatClick}
                />
                {selectedSeat && (
                  <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-slate-800">
                          Seat {selectedSeat.seatId}
                        </p>
                        <p className="truncate text-xs text-slate-500">
                          {selectedSeat.attendeeName
                            ? `${selectedSeat.attendeeName}${selectedSeat.attendeeTitle ? ` · ${selectedSeat.attendeeTitle}` : ""}`
                            : "No attendee checked in"}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => handleSetSpeaker(selectedSeat.seatId)}
                          disabled={!canControlSpeaker(meetingStatus) || speakerBusy || speakerSeatId === selectedSeat.seatId}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {speakerBusy ? <Loader2 size={12} className="animate-spin" /> : <Mic size={13} />}
                          Set Speaker
                        </button>
                        <button
                          onClick={handleClearSpeaker}
                          disabled={!canControlSpeaker(meetingStatus) || speakerBusy || speakerSeatId == null}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {speakerBusy ? <Loader2 size={12} className="animate-spin" /> : <MicOff size={13} />}
                          Clear Speaker
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Right column — full width when conference table is hidden */}
          <div className={`col-span-12 flex flex-col gap-6 ${isEndedMeeting ? '' : 'xl:col-span-4'}`}>
            <SectionCard
              title="Attendees"
              headerRight={
                <span className="text-xs text-slate-400 font-medium">
                  {attendees.length} people
                </span>
              }
            >
              <div className="space-y-3">
                {canManageAttendees(meetingStatus) && (
                  <>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-1">
                      <input
                        type="text"
                        value={attendeeName}
                        onChange={(e) => setAttendeeName(e.target.value)}
                        placeholder="Attendee name"
                        className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-400 focus:border-transparent"
                      />
                      <input
                        type="text"
                        value={attendeeTitle}
                        onChange={(e) => setAttendeeTitle(e.target.value)}
                        placeholder="Title"
                        className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-400 focus:border-transparent"
                      />
                    </div>
                    <button
                      onClick={handleCreateAttendee}
                      disabled={!canManageAttendees(meetingStatus) || attendeeBusy}
                      className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-sky-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {attendeeBusy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={13} />}
                      Add Attendee
                    </button>
                  </>
                )}
                <div className="max-h-48 space-y-1 overflow-y-auto pr-1">
                  {attendees.map((attendee) => (
                    <div
                      key={attendee.id}
                      className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-slate-700">
                          {attendee.name}
                        </p>
                        <p className="truncate text-xs text-slate-400">
                          {attendee.title || "No title"}
                          {attendee.seat_id != null ? ` · Seat ${attendee.seat_id}` : ""}
                        </p>
                      </div>
                      {canManageAttendees(meetingStatus) && (
                        <button
                          onClick={() => handleDeleteAttendee(attendee.id)}
                          disabled={attendeeBusy}
                          className="inline-flex shrink-0 items-center justify-center rounded-md p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50"
                          aria-label={`Delete attendee ${attendee.name}`}
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </SectionCard>

            <div className={uiPhase === "agenda_discussion" ? "border-2 border-amber-300 rounded-xl bg-amber-50 p-3 space-y-3" : "space-y-3"}>
              {uiPhase === "agenda_discussion" && (
                <p className="text-xs font-semibold text-amber-800 flex items-center gap-1.5">
                  <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
                  Agenda Discussion Mode — Agenda items are emphasised below.
                </p>
              )}
              {canManageAgenda(meetingStatus) && (
                <SectionCard title="Add Agenda">
                  <div className="space-y-3">
                    <input
                      type="text"
                      value={agendaTitle}
                      onChange={(e) => setAgendaTitle(e.target.value)}
                      placeholder="Agenda title"
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-400 focus:border-transparent"
                    />
                    <button
                      onClick={handleCreateAgenda}
                      disabled={!canManageAgenda(meetingStatus) || agendaBusy}
                      className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-sky-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {agendaBusy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={13} />}
                      Add Agenda
                    </button>
                  </div>
                </SectionCard>
              )}

              <AgendaPanel
                agenda={agenda}
                onDelete={canManageAgenda(meetingStatus) ? handleDeleteAgenda : undefined}
                deleting={agendaBusy}
              />
            </div>

            {/* Admin action error */}
            {adminActionError && (
              <div className="bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 flex items-center gap-2">
                <AlertCircle size={14} className="text-rose-500 flex-shrink-0" />
                <p className="text-xs text-rose-700">{adminActionError}</p>
                <button
                  onClick={() => setAdminActionError(null)}
                  className="ml-auto text-rose-400 hover:text-rose-600"
                >
                  <XCircle size={14} />
                </button>
              </div>
            )}

            {/* Create Vote form — only when no active vote and meeting is active */}
            {canCreateVote(meetingStatus, voteState, false) && (
              <SectionCard title="Create Vote">
                <div className="space-y-3">
                  <input
                    type="text"
                    value={createVoteTitle}
                    onChange={(e) => setCreateVoteTitle(e.target.value)}
                    placeholder="Vote title..."
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-400 focus:border-transparent"
                  />
                  {createVoteOptions.map((opt, i) => (
                    <input
                      key={i}
                      type="text"
                      value={opt}
                      onChange={(e) => {
                        const next = [...createVoteOptions];
                        next[i] = e.target.value;
                        setCreateVoteOptions(next);
                      }}
                      placeholder={`Option ${i + 1}`}
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-400 focus:border-transparent"
                    />
                  ))}
                  <button
                    onClick={() => setCreateVoteOptions([...createVoteOptions, ""])}
                    className="text-xs font-medium text-sky-600 hover:text-sky-700"
                  >
                    + Add option
                  </button>
                  <label className="flex items-center gap-2 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={createVoteAnonymous}
                      onChange={(e) => setCreateVoteAnonymous(e.target.checked)}
                      className="rounded border-slate-300"
                    />
                    Anonymous vote
                  </label>
                  <button
                    onClick={handleCreateVote}
                    disabled={!canCreateVote(meetingStatus, voteState, creatingVote)}
                    className="w-full inline-flex items-center justify-center gap-2 text-xs font-medium bg-sky-600 text-white rounded-lg px-4 py-2 hover:bg-sky-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {creatingVote ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Vote size={14} />
                    )}
                    {creatingVote ? "Creating..." : "Create Vote"}
                  </button>
                </div>
              </SectionCard>
            )}

            <VotePanel
              vote={activeVote}
              voteResults={voteResults}
              hasActiveVote={hasActiveVote}
              voteStatsError={voteStatsError}
              onRetryStats={refresh}
              onCloseVote={canCloseVote(meetingStatus, voteState, closingVote) ? handleCloseVote : undefined}
              closingVote={closingVote}
            />
            <MeetingResultPanel voteResults={voteResults} />
            <ServicePanel calls={serviceCalls} seatNameMap={seatNameMap} onResolve={canResolveServiceCall(meetingStatus, serviceCalls.some(c => c.status === "pending")) ? handleResolveCall : undefined} resolvingId={resolvingId} />
          </div>
        </div>

        {/* Transcript row */}
        <div className="mt-6">
          <TranscriptPanel
            entries={translations}
            interims={Object.values(interimMap)}
            seatNameMap={seatNameMap}
          />
        </div>
      </main>

      {/* Disconnected overlay — not shown for ended meetings (no WS needed) */}
      {!isEndedMeeting && connection === "disconnected" && (
        <div className="fixed inset-0 bg-white/80 backdrop-blur-sm flex flex-col items-center justify-center z-50">
          <div className="w-14 h-14 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mb-4">
            <div className="text-red-500">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="1" y1="1" x2="23" y2="23" />
                <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
                <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
                <path d="M10.71 5.05A16 16 0 0 1 22.56 9" />
                <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
                <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
                <line x1="12" y1="20" x2="12.01" y2="20" />
              </svg>
            </div>
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

// ── Metric Card ─────────────────────────────────────────────────────────────

interface MetricCardProps {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}

function MetricCard({
  label,
  value,
  sub,
  accent = "text-slate-800",
}: MetricCardProps) {
  return (
    <div className="min-w-0 bg-white rounded-xl border border-slate-200 shadow-sm px-3 sm:px-4 py-3 text-center">
      <p className={`truncate text-xl sm:text-2xl font-bold leading-none ${accent}`}>{value}</p>
      <p className="text-xs font-medium text-slate-500 mt-1">{label}</p>
      {sub && <p className="truncate text-[10px] text-slate-400 mt-0.5">{sub}</p>}
    </div>
  );
}
