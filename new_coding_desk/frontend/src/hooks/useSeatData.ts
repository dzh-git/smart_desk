// ─── Seat Data Hook ────────────────────────────────────────────────────────
// Orchestrates initialisation, API fetching, and WebSocket-driven refreshes
// for a single seat tablet.
//
// Initialisation flow:
//   1. Fetch active meeting, seats, speaker seat, active vote (parallel)
//   2. If active meeting exists → fetch attendees, agendas, current service
//      call, translation history (parallel)
//   3. Attendee list is used for seat mapping and check-in attendee selection
//
// WebSocket connects as /ws/{meeting_id}?seat={seat_id} per protocol.
// Disconnected state → show overlay + disable writes.

import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchActiveMeeting,
  fetchSeats,
  fetchSpeakerSeat,
  fetchActiveVote,
  fetchVoteStatistics,
  fetchAgendas,
  fetchAttendees,
  fetchCurrentServiceCall,
  fetchTranslations,
} from "../api/resources";
import { buildSeatDisplays } from "../api/adapters";
import { useWebSocket } from "./useWebSocket";
import type { WSMessage } from "./useWebSocket";
import type { ConnectionStatus, SeatDisplay } from "../types";
import type {
  Meeting,
  Attendee,
  Agenda,
  Vote,
  VoteStatistics,
  ServiceCall,
  TranslationRecord,
} from "../api/types";

// ── Public interface ────────────────────────────────────────────────────────

export interface SeatData {
  /** True while the very first fetch is in progress. */
  loading: boolean;
  /** Human-readable error message, or null. */
  error: string | null;
  /** The active meeting, or null when none exists. */
  meeting: Meeting | null;
  /** Always 10 seat displays (vacant seats are included). */
  seats: SeatDisplay[];
  /** Seat ID of the current speaker, or null. */
  speakerSeatId: number | null;
  /** Attendees of the active meeting (empty when no meeting). */
  attendees: Attendee[];
  /** Unbound attendees (no seat_id) for check-in selection. */
  unboundAttendees: Attendee[];
  /** Agenda items sorted by sort_order (empty when no meeting). */
  agenda: Agenda[];
  /** The active (open) vote, or null. */
  activeVote: Vote | null;
  /** Vote statistics for the active vote, or null. */
  voteStats: VoteStatistics | null;
  /** True when vote statistics fetch failed. */
  voteStatsError: string | null;
  /** Current pending service call for this seat, or null. */
  currentServiceCall: ServiceCall | null;
  /** Translation history (empty when no meeting). */
  translations: TranslationRecord[];
  /** WebSocket connection status. */
  connection: ConnectionStatus;
  /** True when there is no active meeting (idle/waiting state). */
  noMeeting: boolean;

  /** Manual full re-initialisation. */
  refresh: () => void;
}

// ── Internal state ──────────────────────────────────────────────────────────

interface DataState {
  meeting: Meeting | null;
  seats: SeatDisplay[];
  speakerSeatId: number | null;
  attendees: Attendee[];
  agenda: Agenda[];
  activeVote: Vote | null;
  voteStats: VoteStatistics | null;
  currentServiceCall: ServiceCall | null;
  translations: TranslationRecord[];
}

const EMPTY_DATA: DataState = {
  meeting: null,
  seats: buildSeatDisplays([], [], null),
  speakerSeatId: null,
  attendees: [],
  agenda: [],
  activeVote: null,
  voteStats: null,
  currentServiceCall: null,
  translations: [],
};

// ── Hook ────────────────────────────────────────────────────────────────────

export function useSeatData(seatId: number): SeatData {
  const [data, setData] = useState<DataState>(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectMeetingId, setConnectMeetingId] = useState<number | null>(null);
  const [voteStatsError, setVoteStatsError] = useState<string | null>(null);

  // Track if a refresh is in flight to avoid races
  const fetchingRef = useRef(false);

  // ── Core fetch function ────────────────────────────────────────────────

  const doFetch = useCallback(async (isInitial: boolean) => {
    if (fetchingRef.current) return;
    fetchingRef.current = true;

    if (isInitial) setLoading(true);
    setError(null);
    setVoteStatsError(null);

    try {
      // Step 1: Independent resources (no meeting_id needed)
      const [meeting, seatStates, speaker, rawActiveVote] = await Promise.all([
        fetchActiveMeeting(),
        fetchSeats(),
        fetchSpeakerSeat(),
        fetchActiveVote(),
      ]);

      const meetingId = meeting?.id ?? null;

      // Step 2: Meeting-dependent resources
      let attendees: Attendee[] = [];
      let agenda: Agenda[] = [];
      let currentServiceCall: ServiceCall | null = null;
      let translations: TranslationRecord[] = [];

      if (meetingId) {
        // Fetch attendees, agendas, and translations in parallel (no duplicates)
        const [a, ag, tr] = await Promise.all([
          fetchAttendees(meetingId),
          fetchAgendas(meetingId),
          fetchTranslations(meetingId).then((r) => r.entries),
        ]);
        attendees = a;
        agenda = ag;
        translations = tr;

        // Fetch current service call separately with tolerance for failure
        try {
          currentServiceCall = await fetchCurrentServiceCall(meetingId, seatId);
        } catch {
          currentServiceCall = null;
        }
      }

      // Step 3: Vote data
      const activeVote: Vote | null = rawActiveVote;
      let voteStats: VoteStatistics | null = null;

      if (rawActiveVote) {
        try {
          voteStats = await fetchVoteStatistics(rawActiveVote.id);
        } catch {
          // Statistics fetch failed — expose the error
          setVoteStatsError("Failed to load vote statistics");
        }
      }

      // Build seat displays
      const seats = buildSeatDisplays(seatStates, attendees, speaker);

      setData({
        meeting,
        seats,
        speakerSeatId: speaker.seat_id,
        attendees,
        agenda,
        activeVote,
        voteStats,
        currentServiceCall,
        translations,
      });

      // Update WebSocket meeting target
      setConnectMeetingId(meetingId);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "An unknown error occurred";
      setError(msg);
    } finally {
      fetchingRef.current = false;
      setLoading(false);
    }
  }, [seatId]);

  // ── Initial load ───────────────────────────────────────────────────────

  useEffect(() => {
    doFetch(true);
  }, [doFetch]);

  // ── WebSocket event handler ────────────────────────────────────────────

  const handleWSEvent = useCallback(
    (_event: string, _message: WSMessage) => {
      // Full refresh on any WebSocket event per protocol
      doFetch(false);
    },
    [doFetch],
  );

  const connection = useWebSocket(connectMeetingId, handleWSEvent, seatId);

  // ── Derived data ───────────────────────────────────────────────────────

  // Unbound attendees = those not checked in to any seat
  const unboundAttendees = data.attendees.filter(
    (a) => a.seat_id == null && !a.checked_in,
  );

  // ── Expose ─────────────────────────────────────────────────────────────

  return {
    loading,
    error,
    meeting: data.meeting,
    seats: data.seats,
    speakerSeatId: data.speakerSeatId,
    attendees: data.attendees,
    unboundAttendees,
    agenda: data.agenda,
    activeVote: data.activeVote,
    voteStats: data.voteStats,
    voteStatsError,
    currentServiceCall: data.currentServiceCall,
    translations: data.translations,
    connection,
    noMeeting: !loading && !data.meeting && !error,
    refresh: () => doFetch(false),
  };
}
