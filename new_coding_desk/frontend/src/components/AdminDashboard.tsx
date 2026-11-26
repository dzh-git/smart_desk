import { useState, useCallback, useEffect, useRef, type ReactNode } from "react";
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
  UserCheck,
  Orbit,
  ListChecks,
  Bell,
  Users,
  Captions,
  MoreHorizontal,
  Monitor,
  ArrowRight,
  X,
} from "lucide-react";
import { useAdminData } from "../hooks/useAdminData";
import { SpatialStage } from "../spatial/SpatialStage";
import type { SpatialState } from "../spatial/sceneState";
import "./admin-focus.css";

import { AdminHeader } from "./AdminHeader";
import { ConferenceTable } from "./ConferenceTable";
import { AgendaPanel } from "./AgendaPanel";
import { VotePanel } from "./VotePanel";
import { ServicePanel } from "./ServicePanel";
import { TranscriptPanel } from "./TranscriptPanel";
import { MeetingResultPanel } from "./MeetingResultPanel";
import { HostDisplayControl } from "./HostDisplayControl";
import type { HostTabletDisplayAccess } from "./HostDisplayControl";
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
  fetchPeople,
  deleteAttendee,
  createAgenda,
  deleteAgenda,
  setCurrentAgenda,
  advanceAgenda,
  completeAgenda,
  skipAgenda,
  triggerSpeechPreload,
  setSeatAssignment,
  clearSeatAssignment,
  manualAdmitSeat,
  reportTabletHeartbeat,
} from "../api/resources";
import type { Attendee, Person, TabletHeartbeatPayload } from "../api/types";
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

export interface HostTabletAccess extends HostTabletDisplayAccess {
  heartbeat?: Omit<TabletHeartbeatPayload, "meetingWebsocketStatus">;
}

interface AdminDashboardProps {
  onSwitchToSeat?: (seatId: number) => void;
  hostTabletAccess?: HostTabletAccess;
  hostSeatCheckIn?: ReactNode;
  hostSpeechControl?: ReactNode;
}
const WORKSPACES = [
  ["overview", "会场", "Overview", Orbit],
  ["agenda", "议程", "Agenda", ListChecks],
  ["vote", "投票", "Voting", Vote],
  ["people", "人员", "People", Users],
  ["service", "服务", "Services", Bell],
  ["records", "记录", "Records", Captions],
] as const;

type AdminWorkspace = typeof WORKSPACES[number][0];

const DEFAULT_VOTE_TITLE = "是否通过当前议题？ / Approve Current Agenda Item?";
const DEFAULT_VOTE_OPTIONS = [
  "同意 / Approve",
  "反对 / Reject",
  "弃权 / Abstain",
] as const;


export function AdminDashboard({
  onSwitchToSeat,
  hostTabletAccess,
  hostSeatCheckIn,
  hostSpeechControl,
}: AdminDashboardProps) {
  const {
    loading,
    error,
    meeting,
    pendingMeeting,
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
    liveFinal,
    interimMap,
    lyricMap,
    pendingFinalMap,
    connection,
    noMeeting,
    isEndedMeeting,
    refresh,
    clearEndedMeeting,
  } = useAdminData();

  useEffect(() => {
    const heartbeatProfile = hostTabletAccess?.heartbeat;
    if (!hostTabletAccess || !heartbeatProfile) return;

    let active = true;
    const heartbeat = async () => {
      if (!active) return;
      try {
        await reportTabletHeartbeat(
          hostTabletAccess.deviceId,
          {
            ...heartbeatProfile,
            meetingWebsocketStatus: connection.toUpperCase() as
              TabletHeartbeatPayload["meetingWebsocketStatus"],
          },
          hostTabletAccess.token,
        );
      } catch {
        // Staleness in hardware status represents a missed heartbeat.
      }
    };

    void heartbeat();
    const timer = window.setInterval(heartbeat, 15_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [connection, hostTabletAccess]);

  const [activeSeatId, setActiveSeatId] = useState<number | undefined>();
  const previewSeat = 2;

  // ── Admin action state ─────────────────────────────────────────────────
  const [createVoteTitle, setCreateVoteTitle] = useState(DEFAULT_VOTE_TITLE);
  const [createVoteOptions, setCreateVoteOptions] = useState<string[]>(() => [
    ...DEFAULT_VOTE_OPTIONS,
  ]);
  const [createVoteAnonymous, setCreateVoteAnonymous] = useState(false);
  const [creatingVote, setCreatingVote] = useState(false);
  const [closingVote, setClosingVote] = useState(false);
  const [adminActionError, setAdminActionError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<number | null>(null);
  const [meetingTitle, setMeetingTitle] = useState("");
  const [meetingDescription, setMeetingDescription] = useState("");
  const [meetingActionBusy, setMeetingActionBusy] = useState(false);
  const [speakerBusy, setSpeakerBusy] = useState(false);
  const [attendeeName, setAttendeeName] = useState("");
  const [attendeeTitle, setAttendeeTitle] = useState("");
  const [registeredPeople, setRegisteredPeople] = useState<Person[] | null>(null);
  const [loadingPeople, setLoadingPeople] = useState(false);
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [attendeeBusy, setAttendeeBusy] = useState(false);
  const [seatAccessBusy, setSeatAccessBusy] = useState(false);
  const [agendaBusy, setAgendaBusy] = useState(false);
  const [displayStatusRefresh, setDisplayStatusRefresh] = useState(0);

  // ── Derived meeting lifecycle & vote state (Task 4) ─────────────────────
  const meetingStatus = deriveMeetingLifecycleStatus(meeting, pendingMeeting, isEndedMeeting);
  const rosterMeetingId = pendingMeeting?.id ?? meeting?.id;
  const canEditRoster = canManageAttendees(meetingStatus);
  const voteState = deriveAdminVoteState(hasActiveVote, voteResults);
  const registeredNameCounts = new Map<string, number>();
  registeredPeople?.forEach(({ name }) => {
    registeredNameCounts.set(name, (registeredNameCounts.get(name) ?? 0) + 1);
  });

  // ── AdminWorkspace (local host-only state) ─────────────────────────────
  const [workspace, setWorkspace] = useState<AdminWorkspace>(isEndedMeeting ? "vote" : "overview");
  const workspaceContent = useRef<HTMLElement>(null);

  useEffect(() => {
    setWorkspace(isEndedMeeting ? "vote" : "overview");
  }, [isEndedMeeting, meeting?.id]);

  useEffect(() => {
    if (workspaceContent.current) workspaceContent.current.scrollTop = 0;
  }, [workspace]);

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
      setCreateVoteTitle(DEFAULT_VOTE_TITLE);
      setCreateVoteOptions([...DEFAULT_VOTE_OPTIONS]);
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
      await createMeeting(title, meetingDescription);
      await refresh();
      setMeetingTitle("");
      setMeetingDescription("");
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to create meeting");
    } finally {
      setMeetingActionBusy(false);
    }
  }, [meetingTitle, meetingDescription, refresh]);

  const handleStartPendingMeeting = useCallback(async () => {
    if (!pendingMeeting) return;
    setMeetingActionBusy(true);
    setAdminActionError(null);
    try {
      await startMeeting(pendingMeeting.id);
      await refresh();
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
      await refresh();
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

  async function loadPeople() {
    setLoadingPeople(true);
    setAdminActionError(null);
    try {
      setRegisteredPeople(await fetchPeople());
    } catch (reason) {
      setAdminActionError(reason instanceof Error ? reason.message : "人员名单加载失败");
    } finally {
      setLoadingPeople(false);
    }
  }

  const handleCreateAttendee = useCallback(async () => {
    if (!rosterMeetingId || !canEditRoster) return;
    const name = attendeeName.trim();
    if (!name) {
      setAdminActionError("Attendee name is required");
      return;
    }
    setAttendeeBusy(true);
    setAdminActionError(null);
    try {
      await createAttendee(rosterMeetingId, name, attendeeTitle, selectedPersonId || undefined);
      setAttendeeName("");
      setAttendeeTitle("");
      setSelectedPersonId("");
      await refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to create attendee");
    } finally {
      setAttendeeBusy(false);
    }
  }, [rosterMeetingId, canEditRoster, attendeeName, attendeeTitle, refresh, selectedPersonId]);

  const handleDeleteAttendee = useCallback(async (attendeeId: number) => {
    if (!rosterMeetingId || !canEditRoster) return;
    setAttendeeBusy(true);
    setAdminActionError(null);
    try {
      await deleteAttendee(rosterMeetingId, attendeeId);
      await refresh();
    } catch (err: unknown) {
      setAdminActionError(err instanceof Error ? err.message : "Failed to delete attendee");
    } finally {
      setAttendeeBusy(false);
    }
  }, [rosterMeetingId, canEditRoster, refresh]);

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
  const selectedAssignedAttendee = selectedSeat
    ? attendees.find(
        (attendee) => attendee.assigned_seat_id === selectedSeat.seatId,
      ) ?? null
    : null;

  const handleSeatAssignment = useCallback(
    async (seatId: number, attendeeId: number | null) => {
      if (!rosterMeetingId || !canEditRoster) return;
      setSeatAccessBusy(true);
      setAdminActionError(null);
      try {
        if (attendeeId == null) {
          await clearSeatAssignment(rosterMeetingId, seatId);
        } else {
          await setSeatAssignment(rosterMeetingId, seatId, attendeeId);
        }
        await refresh();
      } catch (error: unknown) {
        setAdminActionError(
          error instanceof Error ? error.message : "席位默认人员配置失败",
        );
      } finally {
        setSeatAccessBusy(false);
      }
    },
    [rosterMeetingId, canEditRoster, refresh],
  );

  const handleManualAdmit = useCallback(
    async (seatId: number, attendee: Attendee) => {
      if (!window.confirm(`允许 ${attendee.name} 入座席位 ${seatId}？`)) {
        return;
      }
      setSeatAccessBusy(true);
      setAdminActionError(null);
      try {
        await manualAdmitSeat(seatId);
        refresh();
      } catch (error: unknown) {
        setAdminActionError(
          error instanceof Error ? error.message : "人工放行失败",
        );
      } finally {
        setSeatAccessBusy(false);
      }
    },
    [refresh],
  );
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

  const roomSeats = seats.map((seat) => {
    const assigned = attendees.find((attendee) => attendee.assigned_seat_id === seat.seatId);
    return !seat.attendeeName && assigned ? { ...seat, attendeeName: assigned.name } : seat;
  });
  const currentAgenda = agenda.find((topic) => topic.status === "active");
  const workspaceTitle = WORKSPACES.find(([key]) => key === workspace)?.[1];
  const scene: SpatialState = {
    mode: workspace === "agenda" || workspace === "vote" ? "agenda"
      : workspace === "service" || workspace === "records" ? "service" : "room",
    phase: error || adminActionError ? "fault" : isEndedMeeting ? "complete"
      : loading || pendingMeeting ? "busy" : !meeting ? "idle"
      : workspace === "vote" && hasActiveVote ? "vote"
        : workspace === "overview" && Object.keys(interimMap).length ? "speech" : "live",
    level: workspace === "service" ? Math.min(1, pendingRequests / 4)
      : workspace === "vote" && hasActiveVote ? Math.min(1, (activeVote?.total_votes ?? 0) / 9)
      : checkedIn / Math.max(seats.length, 1),
    selectedSeat: activeSeatId,
    signal: [
      meeting?.id ?? pendingMeeting?.id, speakerSeatId,
      currentAgenda?.id,
      activeVote?.total_votes, pendingRequests,
    ].join(":"),
    seats: workspace === "overview" && !isEndedMeeting ? roomSeats.map((seat) => ({
      id: seat.seatId,
      status: seat.isSpeaker ? "speaking" : seat.isCheckedIn ? "ready"
        : seat.attendeeName || !seat.isVacant ? "assigned" : "vacant",
    })) : undefined,
  };
  const workspaceNavigation = (
    <nav className="host-workspaces" aria-label="主持人工作区">
      {WORKSPACES.filter(([key]) => isEndedMeeting ? key !== "overview" : !hostTabletAccess || key !== "people")
        .map(([key, label, english, Icon]) => (
          <button
            key={key}
            type="button"
            aria-label={`${label} / ${english}`}
            aria-pressed={workspace === key}
            onClick={() => setWorkspace(key)}
          >
            <Icon size={18} aria-hidden="true" />
            <span>{label}</span>
            {key === "vote" && hasActiveVote && <i aria-label="投票进行中" />}
            {key === "service" && pendingRequests > 0 && <small>{pendingRequests}</small>}
          </button>
        ))}
    </nav>
  );
  const seatOverview = (
    <section className="host-seats desk-panel">
      <div className="host-seats__heading">
        <h3>会议桌总览 <span className="sr-only">/ Conference Room — Seat Overview</span></h3>
        <span>{checkedIn}/{seats.length} 已签到</span>
      </div>
      <div className="host-seats__body" data-selected={Boolean(selectedSeat)}>
      <ConferenceTable
        seats={roomSeats}
        currentSpeaker={speakerSeatId}
        activeSeat={activeSeatId}
        onSeatClick={handleSeatClick}
        preparing={meetingStatus === "meeting_created"}
      />
      {selectedSeat && (
        <aside className="host-seat-detail" aria-label={`席位 ${selectedSeat.seatId} 操作`}>
          <div className="flex items-center justify-between gap-2">
            <p className="font-semibold text-techText">
              座位 {selectedSeat.seatId} / Seat {selectedSeat.seatId}
            </p>
            <button type="button" className="host-icon-button" onClick={() => setActiveSeatId(undefined)} aria-label="关闭席位操作">
              <X size={15} />
            </button>
          </div>
          <div className="flex flex-col gap-3">
            <div className="min-w-0">
              <p className="truncate text-xs text-techMuted">
                {selectedSeat.attendeeName
                  ? `${selectedSeat.attendeeName}${selectedSeat.attendeeTitle ? ` · ${selectedSeat.attendeeTitle}` : ""}`
                  : "尚未签到 / No Attendee Checked In"}
              </p>
              <label className="mt-3 block text-xs text-techMuted">
                默认人员 / Assigned Attendee
                <select
                  data-testid="seat-assignment-select"
                  className="mt-1 block w-full rounded-lg border border-techBorder bg-techCard px-3 py-2 text-sm text-techText disabled:opacity-50"
                  value={selectedAssignedAttendee?.id ?? ""}
                  onChange={(event) =>
                    void handleSeatAssignment(
                      selectedSeat.seatId,
                      event.target.value
                        ? Number(event.target.value)
                        : null,
                    )
                  }
                  disabled={selectedSeat.isCheckedIn || seatAccessBusy}
                >
                  <option value="">未分配 / Unassigned</option>
                  {attendees.map((attendee) => {
                    const assignedElsewhere =
                      attendee.assigned_seat_id != null &&
                      attendee.assigned_seat_id !== selectedSeat.seatId;
                    return (
                      <option
                        key={attendee.id}
                        value={attendee.id}
                        disabled={assignedElsewhere || attendee.checked_in}
                      >
                        {attendee.name} · {attendee.person_id ? "已绑定人脸" : "未绑定人脸"}
                        {assignedElsewhere
                          ? ` · 已分配席位 ${attendee.assigned_seat_id}`
                          : ""}
                      </option>
                    );
                  })}
                </select>
              </label>
            </div>
            {meetingStatus === "meeting_active" && (
            <div className="flex flex-wrap gap-2">
              <button
                data-testid="manual-admit-button"
                onClick={() => {
                  if (selectedAssignedAttendee) {
                    void handleManualAdmit(
                      selectedSeat.seatId,
                      selectedAssignedAttendee,
                    );
                  }
                }}
                disabled={
                  seatAccessBusy ||
                  selectedSeat.isCheckedIn ||
                  selectedAssignedAttendee == null
                }
                className="inline-flex items-center gap-1.5 rounded-lg bg-techGreen/20 border border-techGreen/40 px-3 py-1.5 text-xs font-medium text-techGreen transition-colors hover:bg-techGreen/30 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {seatAccessBusy ? <Loader2 size={12} className="animate-spin" /> : <UserCheck size={13} />}
                人工放行 / Admit
              </button>
              <button
                onClick={() => handleSetSpeaker(selectedSeat.seatId)}
                disabled={
                  !canControlSpeaker(meetingStatus) ||
                  speakerBusy ||
                  speakerSeatId === selectedSeat.seatId ||
                  !selectedSeat.isCheckedIn
                }
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
            )}
          </div>
        </aside>
      )}
      </div>
    </section>
  );

  const rosterPanel = (
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
        {canEditRoster && (
          <>
            {registeredPeople == null ? (
              <ActionButton variant="secondary" size="sm" onClick={loadPeople} loading={loadingPeople}>
                选用已登记人员 / Choose Registered Person
              </ActionButton>
            ) : (
              <label className="block text-xs font-medium text-techMuted">
                已登记人员 / Registered Person
                <select
                  className="mt-1 block w-full rounded-lg border border-techBorder bg-techSurface px-3 py-2 text-sm text-techText"
                  value={selectedPersonId}
                  onChange={(event) => {
                    const id = event.target.value;
                    setSelectedPersonId(id);
                    setAttendeeName(registeredPeople.find((person) => person.id === id)?.name ?? "");
                  }}
                >
                  <option value="">{registeredPeople.length ? "手动填写姓名" : "暂无登记人员"}</option>
                  {registeredPeople.map((person) => (
                    <option key={person.id} value={person.id} disabled={attendees.some((attendee) => attendee.person_id === person.id)}>
                      {(registeredNameCounts.get(person.name) ?? 0) > 1 ? `${person.name} · ${person.id}` : person.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className={`grid grid-cols-1 gap-2 sm:grid-cols-2 ${hostTabletAccess ? "" : "xl:grid-cols-1"}`}>
              <input
                type="text"
                value={attendeeName}
                onChange={(e) => setAttendeeName(e.target.value)}
                readOnly={Boolean(selectedPersonId)}
                placeholder="参会人姓名 / Attendee name"
                className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
              />
              <input
                type="text"
                value={attendeeTitle}
                onChange={(e) => setAttendeeTitle(e.target.value)}
                placeholder="职务 / Title"
                className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
              />
            </div>
            <ActionButton
              variant="primary"
              size="md"
              icon={attendeeBusy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={13} />}
              onClick={handleCreateAttendee}
              disabled={!attendeeName.trim() || attendeeBusy}
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
                  {(attendee.seat_id ?? attendee.assigned_seat_id) != null
                    ? ` · 座位 ${attendee.seat_id ?? attendee.assigned_seat_id} / Seat ${attendee.seat_id ?? attendee.assigned_seat_id}`
                    : ""}
                </p>
                {attendee.title && <p className="truncate text-xs text-techMuted">{attendee.title}</p>}
              </div>
              {canEditRoster && (
                <button
                  onClick={() => handleDeleteAttendee(attendee.id)}
                  disabled={attendeeBusy || attendee.checked_in}
                  className="inline-flex shrink-0 items-center justify-center rounded-md p-1.5 text-techMuted transition-colors hover:bg-techRose/20 hover:text-techRose disabled:opacity-50 min-h-[32px] min-w-[32px]"
                  aria-label={`删除参会人 ${attendee.name} / Delete attendee ${attendee.name}`}
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </SectionCard>
  );

  const actionNotice = adminActionError && (
    <div role="alert" className="bg-techRose/10 border border-techRose/30 rounded-xl px-4 py-3 flex items-center gap-2">
      <AlertCircle size={14} className="text-techRose flex-shrink-0" />
      <p className="text-xs text-techRose">操作失败 / Operation Failed：{adminActionError}</p>
      <button
        aria-label="关闭错误提示"
        onClick={() => setAdminActionError(null)}
        className="ml-auto text-techRose/60 hover:text-techRose"
      >
        <XCircle size={14} />
      </button>
    </div>
  );

  // ── Loading State ──────────────────────────────────────────────────────
  if (loading) {
    return (
      <div data-spatial-mode={scene.mode} data-spatial-phase={scene.phase} className="desk-page min-h-screen flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() && onSwitchToSeat ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="spatial-command spatial-command--setup mx-auto w-full max-w-[1600px] flex-1 items-center p-4 sm:p-6">
          <SpatialStage state={scene} />
          <div className="spatial-command__rail text-center space-y-4">
            <Loader2 size={32} className="animate-spin text-techCyan mx-auto" />
            <p className="text-sm font-medium text-techMuted">
              正在加载会议数据 / Loading meeting data...
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Error State ────────────────────────────────────────────────────────
  if (error) {
    return (
      <div data-spatial-mode={scene.mode} data-spatial-phase={scene.phase} className="desk-page min-h-screen flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() && onSwitchToSeat ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="spatial-command spatial-command--setup mx-auto w-full max-w-[1600px] flex-1 items-center p-4 sm:p-6">
          <SpatialStage state={scene} />
          <div className="spatial-command__rail text-center space-y-4 max-w-md">
            <div className="w-14 h-14 rounded-full bg-techRose/10 border-2 border-techRose/30 flex items-center justify-center mx-auto">
              <AlertCircle className="text-techRose" size={24} />
            </div>
            <p className="text-sm font-semibold text-techText">
              数据加载失败 / <span>Failed to load data</span>
            </p>
            <p className="text-xs text-techMuted">{error}</p>
            <ActionButton
              variant="primary"
              size="md"
              icon={<RefreshCw size={14} />}
              onClick={refresh}
            >
              重试 / Retry
            </ActionButton>
          </div>
        </div>
      </div>
    );
  }

  if (pendingMeeting) {
    return (
      <div data-spatial-mode={scene.mode} data-spatial-phase={scene.phase} className="desk-page host-shell">
        <AdminHeader title={pendingMeeting.title} meetingStatus="pending" connection={connection} />
        <main className="host-workspace">
          {actionNotice}
          <section className="host-preparation">
            <div>
              <p className="host-eyebrow">待启动会议 <span className="sr-only">Pending Meeting</span></p>
              <h2>安排参会人员和席位</h2>
              {pendingMeeting.description && <p>{pendingMeeting.description}</p>}
            </div>
            <ActionButton
              variant="primary"
              onClick={handleStartPendingMeeting}
              disabled={!canStartMeeting(meetingStatus, true, meetingActionBusy) || attendeeBusy || seatAccessBusy}
              loading={meetingActionBusy}
              icon={<Play size={16} />}
            >
              开始会议 / Start Meeting
            </ActionButton>
          </section>
          <div className="host-setup-grid">
            {seatOverview}
            {rosterPanel}
          </div>
        </main>
      </div>
    );
  }

  // ── No Meeting State ───────────────────────────────────────────────────
  if (noMeeting) {
    return (
      <div data-spatial-mode={scene.mode} data-spatial-phase={scene.phase} className="desk-page min-h-screen flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() && onSwitchToSeat ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <main className="spatial-command spatial-command--setup mx-auto w-full max-w-[1600px] flex-1 items-center p-4 sm:p-6">
          <SpatialStage state={scene} />
          <div className="spatial-command__rail">
            <div className="w-16 h-16 rounded-full bg-techCyan/10 border-2 border-techCyan/30 flex items-center justify-center mx-auto">
              <Cpu className="text-techCyan" size={28} />
            </div>
            <div className="text-center">
              <p className="text-2xl font-semibold text-techText">
                暂无进行中的会议 / <span>No Active Meeting</span>
              </p>
              <p className="text-xs text-techMuted">
                填写会议标题后即可安排席位。
              </p>
            </div>

            {actionNotice}

            <SectionCard title="创建会议" titleEn="CREATE MEETING">
              <div className="space-y-3">
                <input
                  type="text"
                  value={meetingTitle}
                  onChange={(e) => setMeetingTitle(e.target.value)}
                  placeholder="会议标题 / Meeting title"
                  className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
                />
                <textarea
                  value={meetingDescription}
                  onChange={(e) => setMeetingDescription(e.target.value)}
                  placeholder="可选说明 / Optional description"
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
                  创建待启动会议 / Create Pending Meeting
                </ActionButton>
              </div>
            </SectionCard>



            <div className="text-center">
              <ActionButton
                variant="secondary"
                size="sm"
                icon={<RefreshCw size={14} />}
                onClick={refresh}
              >
                刷新 / Refresh
              </ActionButton>
            </div>
          </div>
        </main>
      </div>
    );
  }

  const roomFocused = workspace === "overview" && !isEndedMeeting;
  const voteForm = workspace === "vote" && canCreateVote(meetingStatus, voteState, false) && (
      <SectionCard title="创建投票" titleEn="CREATE VOTE">
        <div className="space-y-3">
          <input
            type="text"
            value={createVoteTitle}
            onChange={(e) => setCreateVoteTitle(e.target.value)}
          placeholder="投票标题 / Vote title..."
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
              placeholder={`选项 ${i + 1} / Option ${i + 1}`}
              className="w-full bg-techSurface border border-techBorder rounded-lg px-4 py-2.5 text-sm text-techText placeholder:text-techMuted/60 focus:outline-none focus:border-techCyan focus:ring-1 focus:ring-techCyan/30 transition-colors"
            />
          ))}
          <button
            onClick={() => setCreateVoteOptions([...createVoteOptions, ""])}
            className="text-xs font-medium text-techCyan hover:text-techCyan/80"
          >
            + 添加选项 / Add option
          </button>
          <label className="flex items-center gap-2 text-xs text-techMuted">
            <input
              type="checkbox"
              checked={createVoteAnonymous}
              onChange={(e) => setCreateVoteAnonymous(e.target.checked)}
              className="rounded border-techBorder bg-techSurface text-techCyan focus:ring-techCyan"
            />
            匿名投票 / Anonymous vote
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
            {creatingVote ? "正在创建 / Creating..." : "创建投票 / Create Vote"}
          </ActionButton>
        </div>
      </SectionCard>
  );

  return (
    <div data-spatial-mode={scene.mode} data-spatial-phase={scene.phase} className="desk-page host-shell">
      <AdminHeader
        title={meeting?.title ?? ""}
        meetingStatus={isEndedMeeting ? "finished" : (meeting?.status ?? "pending")}
        connection={connection}
      />
      <div className="host-toolbar">
        {workspaceNavigation}
        <div className="host-toolbar__actions">
          {isEndedMeeting ? (
            <ActionButton variant="primary" size="sm" icon={<Plus size={14} />} onClick={handleClearEndedMeeting}>
              新会议 / New Meeting
            </ActionButton>
          ) : (
            <>
              <a className="host-toolbar__link" href="/display" target="_blank" rel="noreferrer">
                <Monitor size={16} aria-hidden="true" />
                <span>会议大屏</span>
              </a>
              {hostSpeechControl}
              <details className="host-disclosure">
                <summary
                  className="host-toolbar__link"
                  aria-label="更多会议操作 / More meeting actions"
                  onClick={(event) => {
                    if (!event.currentTarget.closest("details")?.open) {
                      setDisplayStatusRefresh((previous) => previous + 1);
                    }
                  }}
                >
                  <MoreHorizontal size={18} aria-hidden="true" />
                  <span>更多</span>
                </summary>
                <div className="host-disclosure__panel">
                  <HostDisplayControl tabletAccess={hostTabletAccess} statusRefresh={displayStatusRefresh} />
                  {elapsedMs > 0 && <p className="text-xs text-techMuted">会议时长 / Meeting Time · {formatDuration(elapsedMs)}</p>}
                  {isDemoControlsEnabled() && onSwitchToSeat && (
                    <nav aria-label="演示席位预览" className="host-demo-seats">
                      <p>演示席位预览</p>
                      <div>
                        {seats.map(({ seatId }) => (
                          <button
                            key={seatId}
                            type="button"
                            aria-label={`打开席位 ${seatId} / Open seat ${seatId}`}
                            onClick={() => onSwitchToSeat(seatId)}
                          >
                            {seatId}
                          </button>
                        ))}
                      </div>
                    </nav>
                  )}
                  <ActionButton
                    variant="danger"
                    size="sm"
                    icon={<Square size={13} />}
                    onClick={handleEndMeeting}
                    disabled={!canEndMeeting(meetingStatus, meetingActionBusy)}
                    loading={meetingActionBusy}
                  >
                    结束会议 / End Meeting
                  </ActionButton>
                </div>
              </details>
            </>
          )}
        </div>
      </div>

      <main ref={workspaceContent} className="host-workspace" data-workspace={workspace} aria-label={workspaceTitle}>
        {!isEndedMeeting && connection === "disconnected" && (
          <div role="status" className="host-connection-notice">
            <span><WifiOff size={15} /> 实时连接恢复中 / Reconnecting</span>
            <ActionButton variant="secondary" size="sm" onClick={refresh}>立即刷新 / Refresh</ActionButton>
          </div>
        )}
        {actionNotice}

        <section className="host-focus" data-room={roomFocused} aria-label="会议焦点">
          <div className="host-focus__copy">
            {roomFocused ? (
              <>
                <p className="host-eyebrow">当前议题 / Current Topic</p>
                <h2>{currentAgenda?.title ?? "还没有进行中的议题"}</h2>
                <div className="host-focus__actions">
                  <ActionButton size="sm" variant="primary" onClick={() => setWorkspace("agenda")} icon={<ArrowRight size={15} />}>
                    {currentAgenda ? "管理议程" : "选择议题"}
                  </ActionButton>
                  {speakerSeatId != null && (
                    <span className="host-focus__speaker">
                      <Mic size={14} aria-hidden="true" /> {speakerAttendee ?? `席位 ${speakerSeatId}`} 正在发言
                    </span>
                  )}
                </div>
              </>
            ) : (
              <>
                {isEndedMeeting && (
                  <p className="host-eyebrow">会议已结束 / <span>Meeting Ended</span>
                    {elapsedMs > 0 && <span className="host-duration"> · {formatDuration(elapsedMs)}</span>}
                  </p>
                )}
                <h2>{workspaceTitle}</h2>
                {workspace === "service" && pendingRequests > 0 && <p className="host-focus__context">{pendingRequests} 项待处理</p>}
              </>
            )}
          </div>
          <SpatialStage
            className="host-focus__stage"
            state={scene}
            onSelectSeat={roomFocused ? handleSeatClick : undefined}
          />
        </section>

        {roomFocused && (
          <div className="host-room-content">
            {seatOverview}
            {hostSeatCheckIn && <div data-testid="host-checkin-layout-slot">{hostSeatCheckIn}</div>}
          </div>
        )}
        {workspace === "people" && rosterPanel}
        {workspace === "agenda" && (
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
        {workspace === "vote" && (
          <div className="host-vote">
            {voteForm}
            {isEndedMeeting ? <MeetingResultPanel voteResults={voteResults} /> : (!voteForm || voteResults.length > 0) && (
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
            {!isEndedMeeting && voteResults.some((vote) => vote.status === "closed") && (
              <details className="host-vote-history">
                <summary>以往投票结果 / Vote History</summary>
                <MeetingResultPanel voteResults={voteResults} />
              </details>
            )}
          </div>
        )}
        {workspace === "service" && (
          <ServicePanel
            calls={serviceCalls}
            seatNameMap={displaySeatNameMap}
            onResolve={canResolveServiceCall(meetingStatus, pendingRequests > 0) ? handleResolveCall : undefined}
            resolvingId={resolvingId}
          />
        )}
        {workspace === "records" && (
          <TranscriptPanel
            entries={translations}
            liveFinal={liveFinal}
            interims={Object.values(interimMap)}
            lyrics={Object.values(lyricMap).flat()}
            pendingFinals={Object.values(pendingFinalMap)}
            seatNameMap={displaySeatNameMap}
            liveEnabled={!isEndedMeeting && meetingStatus === "meeting_active"}
            liveReconnecting={connection !== "connected"}
          />
        )}
      </main>
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
