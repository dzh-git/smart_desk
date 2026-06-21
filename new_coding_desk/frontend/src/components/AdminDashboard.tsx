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
  WifiOff,
} from "lucide-react";
import { useAdminData } from "../hooks/useAdminData";

import { AdminHeader } from "./AdminHeader";
import { ConferenceTable } from "./ConferenceTable";
import { AgendaPanel } from "./AgendaPanel";
import { VotePanel } from "./VotePanel";
import { ServicePanel } from "./ServicePanel";
import { TranscriptPanel } from "./TranscriptPanel";
import { MeetingResultPanel } from "./MeetingResultPanel";
import { HostDisplayControl } from "./HostDisplayControl";
import {
  SectionCard,
  ActionButton,
} from "./shared";
import { formatDuration, isDemoControlsEnabled, useClock, parseBackendDate } from "./shared";
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
  setCurrentAgenda,
  advanceAgenda,
  completeAgenda,
  skipAgenda,
  triggerSpeechPreload,
} from "../api/resources";
import type { Meeting, Attendee } from "../api/types";
import {
  deriveMeetingLifecycleStatus,
  deriveAdminVoteState,
  canCreateMeeting,
  canStartMeeting,
  canEndMeeting,
  canCreateVote,
  canCloseVote,
  canControlSpeaker,
  canManageAttendees,
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
  const [agendaBusy, setAgendaBusy] = useState(false);

  // ── Derived meeting lifecycle & vote state (Task 4) ─────────────────────
  const meetingStatus = deriveMeetingLifecycleStatus(meeting, pendingMeeting, isEndedMeeting);
  const voteState = deriveAdminVoteState(hasActiveVote, voteResults);

  // ── AdminWorkspace (local host-only state) ─────────────────────────────
  type AdminWorkspace = "overview" | "agenda_vote" | "service_records";
  const [workspace, setWorkspace] = useState<AdminWorkspace>("overview");

  // ── Ended Meeting Snapshot ────────────────────────────────────────────────
  // Keep a ref to the latest attendees so handleEndMeeting can snapshot
  // the seat→attendee binding before the backend clears seat_id.
  const attendeesRef = useRef(attendees);
  useEffect(() => { attendeesRef.current = attendees; }, [attendees]);

  // ── Auto speech model preload ───────────────────────────────────────────
  const preloadedMeetingIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (meetingStatus !== "meeting_active" || !meeting?.id) return;
    if (preloadedMeetingIdRef.current === meeting.id) return;

    preloadedMeetingIdRef.current = meeting.id;
    triggerSpeechPreload().catch((error) => {
      console.warn("Speech model preload failed", error);
    });
  }, [meetingStatus, meeting?.id]);

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
      // Save seat→attendee snapshot BEFORE ending the meeting (backend may clear seat_id)
      saveEndedSnapshot(meeting.id, attendeesRef.current);
      const endedMeeting = await endMeeting(meeting.id);
      // Save ended meeting data so the hook can restore it when fetchActiveMeeting returns null
      try {
        sessionStorage.setItem('endedMeetingId', String(meeting.id));
        sessionStorage.setItem('endedMeetingTitle', meeting.title);
        if (meeting.started_at) {
          sessionStorage.setItem('endedMeetingStartedAt', meeting.started_at);
        }
        // Prefer backend ended_at from the API response; fallback to current frontend time.
        sessionStorage.setItem('endedMeetingEndedAt', endedMeeting.ended_at ?? new Date().toISOString());
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

  const handleClearEndedMeeting = useCallback(() => {
    // Clear the snapshot for this meeting too
    if (meeting?.id) {
      try {
        sessionStorage.removeItem(`smartdesk.admin.endedMeetingSnapshot.${meeting.id}`);
      } catch { /* sessionStorage may throw */ }
    }
    // Clear elapsed time data
    try {
      sessionStorage.removeItem('endedMeetingStartedAt');
      sessionStorage.removeItem('endedMeetingEndedAt');
    } catch { /* sessionStorage may throw */ }
    clearEndedMeeting();
  }, [meeting?.id, clearEndedMeeting]);

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

  const handleCreateAgenda = useCallback(async (title: string) => {
    if (!meeting) return;
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setAdminActionError("Agenda title is required");
      return;
    }
    setAgendaBusy(true);
    setAdminActionError(null);
    try {
      await createAgenda(meeting.id, trimmedTitle, agenda.length + 1);
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to create agenda");
    } finally {
      setAgendaBusy(false);
    }
  }, [meeting, agenda.length, refresh]);

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

  const handleSetCurrentAgenda = useCallback(async (agendaId: number) => {
    if (!meeting) return;
    // If there's already an active agenda, confirm before switching
    const activeAgenda = agenda.find((a) => a.status === "active");
    if (activeAgenda) {
      const confirmed = window.confirm(
        `当前议题 "${activeAgenda.title}" 将自动完成并切换到新议题。\n\nThe current topic "${activeAgenda.title}" will be completed and a new topic will be activated.`,
      );
      if (!confirmed) return;
    }
    setAgendaBusy(true);
    setAdminActionError(null);
    try {
      await setCurrentAgenda(meeting.id, agendaId);
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to set current agenda");
    } finally {
      setAgendaBusy(false);
    }
  }, [meeting, agenda, refresh]);

  const handleAdvanceAgenda = useCallback(async () => {
    if (!meeting) return;
    setAgendaBusy(true);
    setAdminActionError(null);
    try {
      await advanceAgenda(meeting.id);
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to advance agenda");
    } finally {
      setAgendaBusy(false);
    }
  }, [meeting, refresh]);

  const handleCompleteAgenda = useCallback(async (agendaId: number) => {
    if (!meeting) return;
    setAgendaBusy(true);
    setAdminActionError(null);
    try {
      await completeAgenda(meeting.id, agendaId);
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to complete agenda");
    } finally {
      setAgendaBusy(false);
    }
  }, [meeting, refresh]);

  const handleSkipAgenda = useCallback(async (agendaId: number) => {
    if (!meeting) return;
    const confirmed = window.confirm(
      `确定跳过当前议题？可稍后重新设为当前议题。\n\nSkip this topic? It can be set as current again later.`,
    );
    if (!confirmed) return;
    setAgendaBusy(true);
    setAdminActionError(null);
    try {
      await skipAgenda(meeting.id, agendaId);
      refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to skip agenda");
    } finally {
      setAgendaBusy(false);
    }
  }, [meeting, refresh]);

  function handleSeatClick(seatId: number) {
    setActiveSeatId((prev) => (prev === seatId ? undefined : seatId));
  }

  // ── Ended meeting snapshot merge ─────────────────────────────────────────
  // When the meeting ends, the backend may set attendee.seat_id to null.
  // Restore the seat→attendee binding from a snapshot saved before endMeeting.
  const endedSnapshot: EndedSnapshot | null =
    isEndedMeeting && meeting?.id ? loadEndedSnapshot(meeting.id) : null;
  const displayAttendees = isEndedMeeting && endedSnapshot
    ? mergeAttendeesWithSnapshot(attendees, endedSnapshot)
    : attendees;

  // Build seat → name map from (possibly merged) attendees
  const displaySeatNameMap: Record<number, string> = {};
  for (const a of displayAttendees) {
    if (a.seat_id != null) {
      displaySeatNameMap[a.seat_id] = a.name;
    }
  }

  // Metric card data
  const checkedIn = displayAttendees.filter((a) => a.checked_in).length;
  const speakerAttendee =
    speakerSeatId != null ? displaySeatNameMap[speakerSeatId] ?? null : null;
  const pendingRequests = serviceCalls.filter(
    (c) => c.status === "pending",
  ).length;
  const selectedSeat = activeSeatId != null
    ? seats.find((s) => s.seatId === activeSeatId)
    : undefined;
  // ── Dynamic elapsed time ────────────────────────────────────────
  // Re-computed every second via useClock so the elapsed display ticks.
  // For ended meetings, use the static duration (started_at → ended_at)
  // so elapsed does not continue ticking after the meeting ends.
  // All backend timestamps are parsed via parseBackendDate to correctly
  // handle naive UTC strings (no "Z" suffix) as UTC rather than local time.
  const clockNow = useClock();
  const elapsedMs = (() => {
    // 1) Try real meeting.started_at
    const startDate = meeting?.started_at ? parseBackendDate(meeting.started_at) : null;
    if (startDate) {
      const startMs = startDate.getTime();
      if (meeting?.ended_at) {
        // Static: ended meeting with real ended_at from backend
        const endDate = parseBackendDate(meeting.ended_at);
        if (endDate) return endDate.getTime() - startMs;
      }
      // Dynamic: active meeting — ticks every second via useClock
      return clockNow.getTime() - startMs;
    }

    // 2) Ended meeting with sessionStorage fallback (after page refresh
    //    the real meeting object is gone; use what we saved at end time).
    if (isEndedMeeting) {
      try {
        const storedStart = sessionStorage.getItem('endedMeetingStartedAt');
        const storedEnd = sessionStorage.getItem('endedMeetingEndedAt');
        if (storedStart && storedEnd) {
          const s = parseBackendDate(storedStart);
          const e = parseBackendDate(storedEnd);
          if (s && e) return e.getTime() - s.getTime();
        }
      } catch { /* sessionStorage may throw */ }
    }
    return 0;
  })();

  // ── Loading State ──────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-techBg flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4">
            <Loader2 size={32} className="animate-spin text-techCyan mx-auto" />
            <p className="text-sm font-medium text-techMuted">
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
      <div className="min-h-screen bg-techBg flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
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
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="w-full max-w-lg space-y-4">
            <div className="w-16 h-16 rounded-full bg-techCyan/10 border-2 border-techCyan/30 flex items-center justify-center mx-auto">
              <Cpu className="text-techCyan" size={28} />
            </div>
            <div className="text-center">
              <p className="text-base font-bold text-techText">
                No Active Meeting
              </p>
              <p className="text-xs text-techMuted">
                Create a pending meeting, then start it when the room is ready.
              </p>
            </div>

            {adminActionError && (
              <div className="bg-techRose/10 border border-techRose/30 rounded-xl px-4 py-3 flex items-center gap-2">
                <AlertCircle size={14} className="text-techRose flex-shrink-0" />
                <p className="text-xs text-techRose">{adminActionError}</p>
                <button
                  onClick={() => setAdminActionError(null)}
                  className="ml-auto text-techRose/60 hover:text-techRose"
                >
                  <XCircle size={14} />
                </button>
              </div>
            )}

            <SectionCard title="创建会议" titleEn="CREATE MEETING">
              <div className="space-y-3">
                <input
                  type="text"
                  value={meetingTitle}
                  onChange={(e) => setMeetingTitle(e.target.value)}
                  placeholder="Meeting title"
                  className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
                />
                <textarea
                  value={meetingDescription}
                  onChange={(e) => setMeetingDescription(e.target.value)}
                  placeholder="Optional description"
                  rows={3}
                  className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
                />
                <ActionButton
                  variant="primary"
                  size="md"
                  onClick={handleCreateMeeting}
                  disabled={!canCreateMeeting(meetingStatus, !meetingTitle.trim(), meetingActionBusy)}
                  className="w-full"
                  icon={meetingActionBusy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                >
                  Create Pending Meeting
                </ActionButton>
              </div>
            </SectionCard>

            {pendingMeeting && (
              <SectionCard
                title="待启动会议"
                titleEn="PENDING MEETING"
                headerRight={
                  <span className="text-xs font-medium text-techAmber">
                    Ready to start
                  </span>
                }
              >
                <div className="space-y-3">
                  <div>
                    <p className="text-sm font-semibold text-techText">
                      {pendingMeeting.title}
                    </p>
                    {pendingMeeting.description && (
                      <p className="text-xs text-techMuted mt-1">
                        {pendingMeeting.description}
                      </p>
                    )}
                  </div>
                  <ActionButton
                    variant="success"
                    size="md"
                    onClick={handleStartPendingMeeting}
                    disabled={!canStartMeeting(meetingStatus, !!pendingMeeting, meetingActionBusy)}
                    className="w-full"
                    icon={meetingActionBusy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                  >
                    Start Meeting
                  </ActionButton>
                </div>
              </SectionCard>
            )}

            <div className="text-center">
              <ActionButton
                variant="secondary"
                size="sm"
                icon={<RefreshCw size={14} />}
                onClick={refresh}
              >
                Refresh
              </ActionButton>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Active Meeting ─────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-techSurface flex flex-col relative">
      <AdminHeader
        title={meeting?.title ?? ""}
        meetingStatus={meeting?.status ?? "pending"}
        connection={connection}
        onModeSwitch={isDemoControlsEnabled() ? () => onSwitchToSeat(previewSeat) : undefined}
        previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        checkedInCount={checkedIn}
        totalSeats={seats.length}
        speakerSeatId={speakerSeatId}
        speakerName={speakerAttendee}
        elapsedMs={elapsedMs}
        pendingRequestCount={pendingRequests}
        hasActiveVote={hasActiveVote}
      />

      {/* Seat preview selector — only visible in demo mode */}
      {isDemoControlsEnabled() && (
        <div className="bg-techSurface border-t border-techBorder px-4 sm:px-6 py-2 flex flex-wrap items-center gap-3">
          <span className="shrink-0 text-xs text-techMuted font-medium">
            Preview seat:
          </span>
          <div className="flex flex-wrap gap-1.5">
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <button
                key={n}
                onClick={() => setPreviewSeat(n)}
                className={`w-7 h-7 rounded-md text-xs font-semibold transition-colors ${
                  previewSeat === n
                    ? "bg-techCyan text-techBg"
                    : "bg-techCard text-techMuted hover:bg-techCardSoft hover:text-techText"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          <ActionButton
            variant="secondary"
            size="sm"
            onClick={() => onSwitchToSeat(previewSeat)}
          >
            Open Seat Tablet View
          </ActionButton>
        </div>
      )}

      <main className="flex-1 p-4 sm:p-6 overflow-auto">
        {/* Summary row / Ended meeting banner */}
        {isEndedMeeting ? (
          <div className="mb-6">
            <div className="rounded-xl border border-techBorder bg-techCard p-4 text-center shadow-card-glow">
              <p className="text-lg font-bold text-techMuted">Meeting Ended</p>
              <p className="text-sm text-techMuted/70 mt-1">{meeting?.title}</p>
              {elapsedMs > 0 && (
                <p className="text-xs text-techMuted/50 mt-2 font-mono">
                  Duration: {formatDuration(elapsedMs)}
                </p>
              )}
            </div>
          </div>
        ) : (
          <div className="mb-6 space-y-3">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <MetricCard
                label="Meeting time"
                value={elapsedMs > 0 ? formatDuration(elapsedMs) : "—"}
                sub="Elapsed"
                accent="text-techCyan"
              />
              <MetricCard
                label="Checked in"
                value={`${checkedIn}/10`}
                sub="Attendees"
                accent={
                  checkedIn >= 9 ? "text-techGreen" : "text-techAmber"
                }
              />
              <MetricCard
                label="Speaker"
                value={speakerAttendee?.split(" ")[0] ?? "—"}
                sub={speakerAttendee ?? "No active speaker"}
                accent="text-techGreen"
              />
              <MetricCard
                label="Pending service"
                value={pendingRequests}
                sub="Requests"
                accent={
                  pendingRequests > 0 ? "text-techRose" : "text-techMuted"
                }
              />
            </div>


          </div>
        )}

        {isEndedMeeting ? (
          <SectionCard
            title="会议已结束"
            titleEn="MEETING ENDED"
            headerRight={
              <span className="text-xs text-techMuted">
                ID {meeting?.id}
              </span>
            }
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <span className="inline-flex items-baseline gap-1.5">
                  <span className="text-sm text-techMuted">会议已结束，下方显示结果。</span>
                  <span className="text-[0.65rem] font-mono uppercase tracking-wider text-techMuted/60">MEETING ENDED — RESULTS BELOW</span>
                </span>
              </div>
              <ActionButton
                variant="secondary"
                size="sm"
                icon={<Plus size={13} />}
                onClick={handleClearEndedMeeting}
              >
                新会议 / NEW MEETING
              </ActionButton>
            </div>
          </SectionCard>
        ) : (
          <SectionCard
            title="会议控制"
            titleEn="MEETING CONTROL"
            headerRight={
              <span className="text-xs text-techMuted">
                ID {meeting?.id}
              </span>
            }
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-techText">
                  会议控制面板 / ACTIVE MEETING CONTROLS
                </p>
                <p className="text-xs text-techMuted">
                  状态: {meeting?.status === "active" ? "进行中" : meeting?.status} / STATUS: {meeting?.status}
                </p>
              </div>
              <ActionButton
                variant="danger"
                size="sm"
                icon={meetingActionBusy ? <Loader2 size={12} className="animate-spin" /> : <Square size={13} />}
                onClick={handleEndMeeting}
                disabled={!canEndMeeting(meetingStatus, meetingActionBusy)}
                loading={meetingActionBusy}
              >
                结束会议 / END MEETING
              </ActionButton>
            </div>
          </SectionCard>
        )}

        {/* Workspace switcher — always visible */}
        <div className="mb-6">
          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => setWorkspace("overview")}
              className={`px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                workspace === "overview"
                  ? "bg-techCyan text-techBg shadow-cyan-glow"
                  : "bg-techCard border border-techBorder text-techMuted hover:bg-techCardSoft hover:text-techText"
              }`}
            >
              <span className="inline-flex items-baseline gap-1.5">
                <span>会议总览</span>
                <span className="text-[0.65rem] font-mono uppercase tracking-wider opacity-60">OVERVIEW</span>
              </span>
            </button>
            <button
              onClick={() => setWorkspace("agenda_vote")}
              className={`px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                workspace === "agenda_vote"
                  ? "bg-techCyan text-techBg shadow-cyan-glow"
                  : "bg-techCard border border-techBorder text-techMuted hover:bg-techCardSoft hover:text-techText"
              }`}
            >
              <span className="inline-flex items-baseline gap-1.5">
                <span>议程与投票</span>
                <span className="text-[0.65rem] font-mono uppercase tracking-wider opacity-60">AGENDA &amp; VOTE</span>
              </span>
            </button>
            <button
              onClick={() => setWorkspace("service_records")}
              className={`px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                workspace === "service_records"
                  ? "bg-techCyan text-techBg shadow-cyan-glow"
                  : "bg-techCard border border-techBorder text-techMuted hover:bg-techCardSoft hover:text-techText"
              }`}
            >
              <span className="inline-flex items-baseline gap-1.5">
                <span>服务与记录</span>
                <span className="text-[0.65rem] font-mono uppercase tracking-wider opacity-60">SERVICE &amp; RECORDS</span>
              </span>
            </button>
          </div>
        </div>

        {/* adminActionError — always visible regardless of workspace */}
        {adminActionError && (
          <div className="mb-6 bg-techRose/10 border border-techRose/30 rounded-xl px-4 py-3 flex items-center gap-2">
            <AlertCircle size={14} className="text-techRose flex-shrink-0" />
            <p className="text-xs text-techRose">{adminActionError}</p>
            <button
              onClick={() => setAdminActionError(null)}
              className="ml-auto text-techRose/60 hover:text-techRose"
            >
              <XCircle size={14} />
            </button>
          </div>
        )}

        {/* Main content — filtered by workspace for active meetings, all visible for ended meetings */}
        <div className="grid grid-cols-12 gap-6">
          {/* Conference table — only in overview workspace for active meetings */}
          {!isEndedMeeting && workspace === "overview" && (
            <div className="col-span-12 xl:col-span-8">
              <div className="bg-techCard border border-techBorder rounded-lg shadow-card-glow p-6">
                <h3 className="text-xs font-semibold uppercase tracking-widest text-techMuted mb-5">
                  会议桌总览 / Conference Room — Seat Overview
                </h3>
                <ConferenceTable
                  seats={seats}
                  currentSpeaker={speakerSeatId}
                  activeSeat={activeSeatId}
                  onSeatClick={handleSeatClick}
                />
                {selectedSeat && (
                  <div className="mt-5 rounded-lg border border-techBorder bg-techCardSoft p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-techText">
                          座位 {selectedSeat.seatId} / Seat {selectedSeat.seatId}
                        </p>
                        <p className="truncate text-xs text-techMuted">
                          {selectedSeat.attendeeName
                            ? `${selectedSeat.attendeeName}${selectedSeat.attendeeTitle ? ` · ${selectedSeat.attendeeTitle}` : ""}`
                            : "No attendee checked in"}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => handleSetSpeaker(selectedSeat.seatId)}
                          disabled={!canControlSpeaker(meetingStatus) || speakerBusy || speakerSeatId === selectedSeat.seatId}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-techCyan/20 border border-techCyan/40 px-3 py-1.5 text-xs font-medium text-techCyan transition-colors hover:bg-techCyan/30 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {speakerBusy ? <Loader2 size={12} className="animate-spin" /> : <Mic size={13} />}
                          设为发言 / Set Speaker
                        </button>
                        <button
                          onClick={handleClearSpeaker}
                          disabled={!canControlSpeaker(meetingStatus) || speakerBusy || speakerSeatId == null}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-techBorder bg-techCard px-3 py-1.5 text-xs font-medium text-techMuted transition-colors hover:bg-techCardSoft disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {speakerBusy ? <Loader2 size={12} className="animate-spin" /> : <MicOff size={13} />}
                          清除发言 / Clear
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Right column */}
          <div className={`col-span-12 flex flex-col gap-6 ${isEndedMeeting || workspace !== "overview" ? '' : 'xl:col-span-4'}`}>
            {/* Attendees — visible in overview workspace or ended meetings */}
            {(isEndedMeeting || workspace === "overview") && (
              <SectionCard
                title="参会人员"
                titleEn="ATTENDEES"
                headerRight={
                  <span className="text-xs text-techMuted font-medium">
                    {displayAttendees.length} 人 / PEOPLE
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
                          className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
                        />
                        <input
                          type="text"
                          value={attendeeTitle}
                          onChange={(e) => setAttendeeTitle(e.target.value)}
                          placeholder="Title"
                          className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
                        />
                      </div>
                      <ActionButton
                        variant="primary"
                        size="md"
                        icon={attendeeBusy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={13} />}
                        onClick={handleCreateAttendee}
                        disabled={!canManageAttendees(meetingStatus) || attendeeBusy}
                        loading={attendeeBusy}
                        className="w-full"
                      >
                        添加参会人 / ADD ATTENDEE
                      </ActionButton>
                    </>
                  )}
                  <div className="max-h-48 space-y-1 overflow-y-auto pr-1">
                    {displayAttendees.map((attendee) => (
                      <div
                        key={attendee.id}
                        className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-techCardSoft"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-techText">
                            {attendee.name}
                            {attendee.seat_id != null ? ` · Seat ${attendee.seat_id}` : ""}
                          </p>
                          <p className="truncate text-xs text-techMuted">
                            {attendee.title || "No title"}
                          </p>
                        </div>
                        {canManageAttendees(meetingStatus) && (
                          <button
                            onClick={() => handleDeleteAttendee(attendee.id)}
                            disabled={attendeeBusy}
                            className="inline-flex shrink-0 items-center justify-center rounded-md p-1.5 text-techMuted transition-colors hover:bg-techRose/20 hover:text-techRose disabled:opacity-50 min-h-[32px] min-w-[32px]"
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
            )}

            {/* Host Display Control — only in overview for active meetings */}
            {workspace === "overview" && !isEndedMeeting && (
              <HostDisplayControl />
            )}

            {/* AgendaPanel — visible in agenda_vote workspace or ended meetings */}
            {(isEndedMeeting || workspace === "agenda_vote") && (
              <AgendaPanel
                agendas={agenda}
                onSetCurrent={handleSetCurrentAgenda}
                onAdvance={handleAdvanceAgenda}
                onComplete={handleCompleteAgenda}
                onSkip={handleSkipAgenda}
                onDelete={handleDeleteAgenda}
                onAdd={handleCreateAgenda}
                busy={agendaBusy}
                readOnly={isEndedMeeting}
                actionError={adminActionError}
                onClearError={() => setAdminActionError(null)}
                meetingActive={meetingStatus === "meeting_active"}
              />
            )}

            {/* Lightweight empty state for agenda_vote — no agenda and no vote */}
            {workspace === "agenda_vote" && !isEndedMeeting && agenda.length === 0 && voteState === "none" && (
              <p className="text-xs text-techMuted/70 text-center py-3">
                暂无议程与投票内容。下方可添加议程或创建投票。
              </p>
            )}

            {/* VotePanel — visible in agenda_vote workspace or ended meetings */}
            {(isEndedMeeting || workspace === "agenda_vote") && (
              <VotePanel
                vote={activeVote}
                voteResults={voteResults}
                hasActiveVote={hasActiveVote}
                voteStatsError={voteStatsError}
                onRetryStats={refresh}
                onCloseVote={canCloseVote(meetingStatus, voteState, closingVote) ? handleCloseVote : undefined}
                closingVote={closingVote}
              />
            )}

            {/* Create Vote form — only in agenda_vote workspace for active meetings */}
            {workspace === "agenda_vote" && canCreateVote(meetingStatus, voteState, false) && (
              <SectionCard title="创建投票" titleEn="CREATE VOTE">
                <div className="space-y-3">
                  <input
                    type="text"
                    value={createVoteTitle}
                    onChange={(e) => setCreateVoteTitle(e.target.value)}
                    placeholder="Vote title..."
                    className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
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
                      className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
                    />
                  ))}
                  <button
                    onClick={() => setCreateVoteOptions([...createVoteOptions, ""])}
                    className="text-xs font-medium text-techCyan hover:text-techCyan/80"
                  >
                    + Add option
                  </button>
                  <label className="flex items-center gap-2 text-xs text-techMuted">
                    <input
                      type="checkbox"
                      checked={createVoteAnonymous}
                      onChange={(e) => setCreateVoteAnonymous(e.target.checked)}
                      className="rounded border-techBorder bg-techSurface text-techCyan focus:ring-techCyan"
                    />
                    Anonymous vote
                  </label>
                  <ActionButton
                    variant="primary"
                    size="md"
                    icon={creatingVote ? <Loader2 size={14} className="animate-spin" /> : <Vote size={14} />}
                    onClick={handleCreateVote}
                    disabled={!canCreateVote(meetingStatus, voteState, creatingVote)}
                    loading={creatingVote}
                    className="w-full"
                  >
                    {creatingVote ? "Creating..." : "Create Vote"}
                  </ActionButton>
                </div>
              </SectionCard>
            )}

            {/* MeetingResultPanel — visible in agenda_vote workspace or ended meetings */}
            {(isEndedMeeting || workspace === "agenda_vote") && (
              <MeetingResultPanel voteResults={voteResults} />
            )}

            {/* Lightweight empty state for service_records — no service calls and no transcript */}
            {workspace === "service_records" && !isEndedMeeting && serviceCalls.length === 0 && translations.length === 0 && Object.keys(interimMap).length === 0 && (
              <p className="text-xs text-techMuted/70 text-center py-3">
                暂无服务请求与字幕记录。
              </p>
            )}

            {/* ServicePanel — visible in service_records workspace or ended meetings */}
            {(isEndedMeeting || workspace === "service_records") && (
              <ServicePanel calls={serviceCalls} seatNameMap={displaySeatNameMap} onResolve={canResolveServiceCall(meetingStatus, serviceCalls.some(c => c.status === "pending")) ? handleResolveCall : undefined} resolvingId={resolvingId} />
            )}
          </div>
        </div>

        {/* Transcript row — visible in service_records workspace or ended meetings */}
        {(isEndedMeeting || workspace === "service_records") && (
          <div className="mt-6">
            <TranscriptPanel
              entries={translations}
              interims={Object.values(interimMap)}
              seatNameMap={displaySeatNameMap}
            />
          </div>
        )}
      </main>

      {/* Disconnected overlay — not shown for ended meetings (no WS needed) */}
      {!isEndedMeeting && connection === "disconnected" && (
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
  accent = "text-techCyan",
}: MetricCardProps) {
  return (
    <div className="min-w-0 bg-techCard border border-techBorder rounded-lg shadow-card-glow px-3 sm:px-4 py-3 text-center">
      <p className={`truncate text-xl sm:text-2xl font-bold leading-none ${accent}`}>{value}</p>
      <p className="text-xs font-medium text-techMuted mt-1">{label}</p>
      {sub && <p className="truncate text-[10px] text-techMuted/60 mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Ended Meeting Snapshot Helpers ──────────────────────────────────────────
// These are used to preserve seat→attendee bindings when the meeting ends,
// because the backend may set attendee.seat_id to null on endMeeting.

export interface EndedSnapshot {
  meetingId: number;
  attendees: Array<{
    id: number;
    name: string;
    title: string | null;
    seat_id: number | null;
  }>;
}

function saveEndedSnapshot(meetingId: number, attendees: Attendee[]): void {
  const snapshot: EndedSnapshot = {
    meetingId,
    attendees: attendees.map(a => ({
      id: a.id,
      name: a.name,
      title: a.title,
      seat_id: a.seat_id,
    })),
  };
  try {
    sessionStorage.setItem(
      `smartdesk.admin.endedMeetingSnapshot.${meetingId}`,
      JSON.stringify(snapshot),
    );
  } catch { /* sessionStorage may not be available */ }
}

function loadEndedSnapshot(meetingId: number): EndedSnapshot | null {
  try {
    const raw = sessionStorage.getItem(
      `smartdesk.admin.endedMeetingSnapshot.${meetingId}`,
    );
    if (raw) return JSON.parse(raw) as EndedSnapshot;
  } catch { /* ignore parse errors */ }
  return null;
}

function mergeAttendeesWithSnapshot(
  apiAttendees: Attendee[],
  snapshot: EndedSnapshot,
): Attendee[] {
  return apiAttendees.map(apiA => {
    // If API already returned seat_id, prefer it (e.g. backend didn't clear it)
    if (apiA.seat_id != null) return apiA;

    // Match by attendee id (most reliable)
    const byId = snapshot.attendees.find(s => s.id === apiA.id);
    if (byId && byId.seat_id != null) {
      return { ...apiA, seat_id: byId.seat_id };
    }

    // Match by name (fallback, e.g. if the attendee was re-created with a new id)
    const byName = snapshot.attendees.find(s => s.name === apiA.name && s.seat_id != null);
    if (byName) {
      return { ...apiA, seat_id: byName.seat_id };
    }

    return apiA;
  });
}
