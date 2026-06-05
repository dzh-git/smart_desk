// ─── Admin Data Hook ────────────────────────────────────────────────────────
// Orchestrates initialisation, API fetching, and WebSocket-driven refreshes
// for the admin dashboard.
//
// Initialisation flow:
//   1. Fetch active meeting, seats, speaker seat, active vote (parallel)
//   2. If active meeting exists → fetch agendas, attendees, service calls, translations (parallel)
//   3. If active vote exists → fetch statistics
//
// Error handling for vote statistics (Phase 04 review fix):
//   If statistics fetch fails, the error is exposed via `voteStatsError` and
//   `activeVote` remains null. The UI shows a retryable error state instead
//   of silently faking zero results.

import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchActiveMeeting,
  fetchSeats,
  fetchSpeakerSeat,
  fetchActiveVote,
  fetchVoteStatistics,
  fetchAgendas,
  fetchAttendees,
  fetchServiceCalls,
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
  VoteStatistics,
  ServiceCall,
  TranslationRecord,
} from "../api/types";

// ── Public interface ────────────────────────────────────────────────────────

export interface AdminData {
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
  /** Agenda items sorted by sort_order (empty when no meeting). */
  agenda: Agenda[];
  /** Active vote statistics, or null when no active vote or stats fetch failed. */
  activeVote: VoteStatistics | null;
  /** True when the backend reports an active vote but statistics failed to load. */
  hasActiveVote: boolean;
  /** Error message from a failed vote statistics fetch, or null. */
  voteStatsError: string | null;
  /** Service calls for the active meeting (empty when no meeting). */
  serviceCalls: ServiceCall[];
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
  activeVote: VoteStatistics | null;
  serviceCalls: ServiceCall[];
  translations: TranslationRecord[];
}

const EMPTY_DATA: DataState = {
  meeting: null,
  seats: buildSeatDisplays([], [], null),
  speakerSeatId: null,
  attendees: [],
  agenda: [],
  activeVote: null,
  serviceCalls: [],
  translations: [],
};

// ── Hook ────────────────────────────────────────────────────────────────────

export function useAdminData(): AdminData {
  const [data, setData] = useState<DataState>(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectMeetingId, setConnectMeetingId] = useState<number | null>(null);
  const [hasActiveVote, setHasActiveVote] = useState(false);
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
      const voteExists = rawActiveVote != null;
      setHasActiveVote(voteExists);

      // Step 2: Meeting-dependent resources
      let attendees: Attendee[] = [];
      let agenda: Agenda[] = [];
      let serviceCalls: ServiceCall[] = [];
      let translations: TranslationRecord[] = [];

      if (meetingId) {
        const [a, ag, sc, tr] = await Promise.all([
          fetchAttendees(meetingId),
          fetchAgendas(meetingId),
          fetchServiceCalls(meetingId),
          fetchTranslations(meetingId),
        ]);
        attendees = a;
        agenda = ag;
        serviceCalls = sc;
        translations = tr.entries;
      }

      // Step 3: Vote statistics (if active vote)
      let voteStats: VoteStatistics | null = null;
      if (rawActiveVote) {
        try {
          voteStats = await fetchVoteStatistics(rawActiveVote.id);
        } catch (err: unknown) {
          // Statistics fetch failed — do NOT fake zero results.
          // Expose the error so the UI can show a retryable error state.
          const msg =
            err instanceof Error ? err.message : "Failed to load vote statistics";
          setVoteStatsError(msg);
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
        activeVote: voteStats,
        serviceCalls,
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
  }, []);

  // ── Initial load ───────────────────────────────────────────────────────

  useEffect(() => {
    doFetch(true);
  }, [doFetch]);

  // ── WebSocket event handler ────────────────────────────────────────────

  const handleWSEvent = useCallback(
    (_event: string, _message: WSMessage) => {
      // We always trigger a full refresh for simplicity and correctness.
      // According to the protocol, the frontend should re-fetch HTTP state
      // after receiving events. A full refresh is always safe.
      doFetch(false);
    },
    [doFetch],
  );

  const connection = useWebSocket(connectMeetingId, handleWSEvent);

  // ── Expose ─────────────────────────────────────────────────────────────

  return {
    loading,
    error,
    meeting: data.meeting,
    seats: data.seats,
    speakerSeatId: data.speakerSeatId,
    attendees: data.attendees,
    agenda: data.agenda,
    activeVote: data.activeVote,
    hasActiveVote,
    voteStatsError,
    serviceCalls: data.serviceCalls,
    translations: data.translations,
    connection,
    noMeeting: !loading && !data.meeting && !error,
    refresh: () => doFetch(false),
  };
}
