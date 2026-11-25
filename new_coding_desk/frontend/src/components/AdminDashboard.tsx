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

  // ── Derived meeting lifecycle & vote state (Task 4) ─────────────────────
  const meetingStatus = deriveMeetingLifecycleStatus(meeting, pendingMeeting, isEndedMeeting);
  const rosterMeetingId = pendingMeeting?.id ?? meeting?.id;
  const canEditRoster = canManageAttendees(meetingStatus);
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
  const seatOverview = (
    <div className="desk-panel rounded-2xl border border-techBorder bg-techCard p-4 sm:p-6">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-techMuted mb-5">
        会议桌总览 / Conference Room — Seat Overview
      </h3>
      <ConferenceTable
        seats={roomSeats}
        currentSpeaker={speakerSeatId}
        activeSeat={activeSeatId}
        onSeatClick={handleSeatClick}
        preparing={meetingStatus === "meeting_created"}
      />
      {selectedSeat && (
        <div className="mt-5 rounded-lg border border-techBorder bg-techCardSoft p-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-techText">
                座位 {selectedSeat.seatId} / Seat {selectedSeat.seatId}
              </p>
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
        </div>
      )}
    </div>
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
                      {person.name} · {person.id}
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
                <p className="truncate text-xs text-techMuted">
                  {attendee.title || "未填写职务 / No Title"}
                </p>
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
      <div className="desk-page min-h-screen flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() && onSwitchToSeat ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4">
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
      <div className="desk-page min-h-screen flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() && onSwitchToSeat ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4 max-w-md">
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
      <div className="desk-page min-h-screen">
        <AdminHeader title="" meetingStatus="pending" connection={connection} />
        <main className="mx-auto max-w-[1600px] space-y-5 p-4 sm:p-6">
          {actionNotice}
          <SectionCard title="待启动会议" titleEn="Pending Meeting">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="min-w-0">
                <h1 className="break-words text-2xl font-semibold text-techText">{pendingMeeting.title}</h1>
                {pendingMeeting.description && (
                  <p className="mt-1 text-sm text-techMuted">{pendingMeeting.description}</p>
                )}
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
            </div>
          </SectionCard>
          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
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
      <div className="desk-page min-h-screen flex flex-col">
        <AdminHeader
          title=""
          meetingStatus="pending"
          connection={connection}
          onModeSwitch={isDemoControlsEnabled() && onSwitchToSeat ? () => onSwitchToSeat(previewSeat) : undefined}
          previewSeat={isDemoControlsEnabled() ? previewSeat : undefined}
        />
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="desk-hero w-full max-w-2xl space-y-5 rounded-2xl border border-techBorder p-5 sm:p-8">
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
        </div>
      </div>
    );
  }

  // ── Active Meeting ─────────────────────────────────────────────────────
  return (
    <div className="desk-page min-h-screen flex flex-col relative">
      <AdminHeader
        title={meeting?.title ?? ""}
        meetingStatus={meeting?.status ?? "pending"}
        connection={connection}
      />

      {isDemoControlsEnabled() && onSwitchToSeat && (
        <nav aria-label="演示席位预览" className="border-b border-techBorder bg-techSurface/60">
          <div className="mx-auto flex max-w-[1760px] flex-wrap items-center gap-2 px-4 py-2.5 sm:px-6">
            <span className="mr-2 text-xs font-semibold text-techMuted">快速打开席位</span>
            {seats.map(({ seatId }) => (
              <button
                key={seatId}
                type="button"
                aria-label={`打开席位 ${seatId} / Open seat ${seatId}`}
                onClick={() => onSwitchToSeat(seatId)}
                className="min-h-9 min-w-9 rounded-lg border border-techBorder bg-techCard px-2.5 text-sm font-semibold text-techText transition-colors hover:border-techCyan/50 hover:text-techCyan"
              >
                {seatId}
              </button>
            ))}
          </div>
        </nav>
      )}

      <main className="mx-auto w-full max-w-[1760px] flex-1 space-y-5 p-4 sm:p-6">
        {!isEndedMeeting && connection === "disconnected" && (
          <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-techAmber/30 bg-techAmber/10 px-4 py-2 text-sm text-techAmber">
            <span className="inline-flex items-center gap-2"><WifiOff size={14} /> 实时连接恢复中 / Reconnecting</span>
            <ActionButton variant="secondary" size="sm" onClick={refresh}>立即刷新 / Refresh</ActionButton>
          </div>
        )}
        {/* Summary row / Ended meeting banner */}
        {isEndedMeeting ? (
          <div className="mb-6">
            <div className="rounded-xl border border-techBorder bg-techCard p-4 text-center shadow-card-glow">
              <p className="text-lg font-bold text-techMuted">会议已结束 / <span>Meeting Ended</span></p>
              <p className="text-sm text-techMuted/70 mt-1">{meeting?.title}</p>
              {elapsedMs > 0 && (
                <p className="text-xs text-techMuted/50 mt-2 font-mono">
                  会议时长 / Duration: {formatDuration(elapsedMs)}
                </p>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <MetricCard
                labelCn="会议时长"
                labelEn="MEETING TIME"
                value={elapsedMs > 0 ? formatDuration(elapsedMs) : "—"}
                accent="text-techCyan"
              />
              <MetricCard
                labelCn="签到人数"
                labelEn="CHECKED IN"
                value={`${checkedIn}/${seats.length}`}
                detailCn="参会人"
                detailEn="ATTENDEES"
                accent={
                  checkedIn >= 9 ? "text-techGreen" : "text-techAmber"
                }
              />
              <MetricCard
                labelCn="当前发言人"
                labelEn="CURRENT SPEAKER"
                value={speakerAttendee?.split(" ")[0] ?? "—"}
                detailCn={speakerSeatId != null ? `座位 ${speakerSeatId}` : "暂无发言人"}
                detailEn={speakerSeatId != null ? `SEAT ${speakerSeatId}` : "NO ACTIVE SPEAKER"}
                accent="text-techGreen"
              />
              <MetricCard
                labelCn="待处理服务"
                labelEn="PENDING SERVICES"
                value={pendingRequests}
                detailCn="请求"
                detailEn="REQUESTS"
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
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex flex-wrap items-baseline gap-2 text-sm font-semibold text-techText">
              <span>会议控制</span>
              <span className="desk-label">MEETING CONTROL</span>
              <span className="desk-label">· ID {meeting?.id}</span>
            </h2>
            <div className="flex flex-wrap items-center gap-3">
              <a className="rounded-lg border border-techBorder px-3 py-2 text-sm font-semibold text-techCyan hover:border-techCyan/50" href="/display" target="_blank" rel="noreferrer">
                会议大屏 / Display
              </a>
              <ActionButton
                variant="danger"
                size="sm"
                icon={<Square size={13} />}
                onClick={handleEndMeeting}
                disabled={!canEndMeeting(meetingStatus, meetingActionBusy)}
                loading={meetingActionBusy}
              >
                结束会议 / END MEETING
              </ActionButton>
            </div>
          </div>
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
            <p className="text-xs text-techRose">操作失败 / Operation Failed：{adminActionError}</p>
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
            <div className={hostTabletAccess ? "col-span-12" : "col-span-12 xl:col-span-8"}>
              {seatOverview}
            </div>
          )}

          {/* Supporting panels. The host tablet gives these a full-width row below the table. */}
          <div className={`col-span-12 ${
            !isEndedMeeting && workspace === "overview" && hostTabletAccess
              ? "flex flex-col gap-6"
              : `flex flex-col gap-6 ${isEndedMeeting || workspace !== "overview" ? "" : "xl:col-span-4"}`
          }`}>
            {workspace === "overview" && !isEndedMeeting && hostSeatCheckIn && (
              <div className="xl:col-span-2" data-testid="host-checkin-layout-slot">
                {hostSeatCheckIn}
              </div>
            )}

            {/* Attendees — desktop overview management or ended-meeting read-only roster. */}
            {(isEndedMeeting || (workspace === "overview" && !hostTabletAccess)) && (
              rosterPanel
            )}

            {/* Host Display Control — only in overview for active meetings */}
            {workspace === "overview" && !isEndedMeeting && (
              <HostDisplayControl tabletAccess={hostTabletAccess} />
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
                暂无议程与投票内容。下方可添加议程或创建投票。 / No agenda or vote yet. Add an agenda or create a vote below.
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
            )}

            {/* MeetingResultPanel — visible in agenda_vote workspace or ended meetings */}
            {(isEndedMeeting || workspace === "agenda_vote") && (
              <MeetingResultPanel voteResults={voteResults} />
            )}

            {/* Lightweight empty state for service_records — no service calls and no transcript */}
            {workspace === "service_records" && !isEndedMeeting && serviceCalls.length === 0 && translations.length === 0 && Object.keys(interimMap).length === 0 && Object.keys(pendingFinalMap).length === 0 && (
              <p className="text-xs text-techMuted/70 text-center py-3">
                暂无服务请求与字幕记录。 / No service requests or transcript records.
              </p>
            )}

            {/* ServicePanel — visible in service_records workspace or ended meetings */}
            {(isEndedMeeting || workspace === "service_records") && (
              <ServicePanel calls={serviceCalls} seatNameMap={displaySeatNameMap} onResolve={canResolveServiceCall(meetingStatus, serviceCalls.some(c => c.status === "pending")) ? handleResolveCall : undefined} resolvingId={resolvingId} />
            )}
          </div>
        </div>

        {/* Transcript row — visible only in the service_records workspace */}
        {workspace === "service_records" && (
          <div className="mt-6 space-y-4">
            {hostSpeechControl}
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
          </div>
        )}
      </main>


    </div>
  );
}

// ── Metric Card ─────────────────────────────────────────────────────────────

interface MetricCardProps {
  labelCn: string;
  labelEn: string;
  value: string | number;
  detailCn?: string;
  detailEn?: string;
  accent?: string;
}

function MetricCard({
  labelCn,
  labelEn,
  value,
  detailCn,
  detailEn,
  accent = "text-techCyan",
}: MetricCardProps) {
  return (
    <div className="desk-panel min-w-0 rounded-xl border border-techBorder px-4 py-4 sm:px-5">
      <p className={`truncate text-xl sm:text-2xl font-bold leading-none ${accent}`}>{value}</p>
      <p className="mt-2 flex flex-wrap items-baseline gap-1.5 text-xs font-medium text-techMuted">
        <span>{labelCn}</span>
        <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techMuted/70">{labelEn}</span>
      </p>
      {detailCn && (
        <p className="mt-0.5 truncate text-[10px] text-techMuted/60">
          {detailCn}{detailEn ? ` / ${detailEn}` : ""}
        </p>
      )}
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
