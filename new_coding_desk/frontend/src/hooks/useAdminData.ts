// ─── Admin Data Hook ────────────────────────────────────────────────────────
// Orchestrates initialisation, API fetching, and WebSocket-driven refreshes
// for the admin dashboard.
//
// Initialisation flow:
//   1. Fetch active meeting, seats, speaker seat, active vote (parallel)
//   2. If active meeting exists → fetch agendas, attendees, service calls, translations (parallel)
//   3. If active vote exists → fetch statistics
//
// WebSocket event handling:
//   translation_interim           → update interimMap only, no HTTP refresh
//   translation_final             → remove matching interim, full HTTP refresh
//   translation_interim_cancelled → remove matching interim, no HTTP refresh
//   all other events              → full HTTP refresh (existing behaviour)

import { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchActiveMeeting,
  fetchSeats,
  fetchSpeakerSeat,
  fetchActiveVote,
  fetchVoteStatistics,
  fetchVoteResultsForMeeting,
  fetchAgendas,
  fetchAttendees,
  fetchServiceCalls,
  fetchTranslations,
} from "../api/resources";
import { buildSeatDisplays } from "../api/adapters";
import { useWebSocket } from "./useWebSocket";
import type { WSMessage } from "./useWebSocket";
import { trace } from "../audio/speechTrace";
import type { ConnectionStatus, SeatDisplay, InterimTranslation } from "../types";
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
  /** Vote statistics for current and historical meeting votes, newest first. */
  voteResults: VoteStatistics[];
  /** True when the backend reports an active vote but statistics failed to load. */
  hasActiveVote: boolean;
  /** Error message from a failed vote statistics fetch, or null. */
  voteStatsError: string | null;
  /** Service calls for the active meeting (empty when no meeting). */
  serviceCalls: ServiceCall[];
  /** Translation history (empty when no meeting). */
  translations: TranslationRecord[];
  /** Interim translations keyed by utterance_id (not persisted). */
  interimMap: Record<string, InterimTranslation>;
  /** WebSocket connection status. */
  connection: ConnectionStatus;
  /** True when there is no active meeting (idle/waiting state). */
  noMeeting: boolean;

  /** True when viewing an ended meeting's results (no active meeting). */
  isEndedMeeting: boolean;

  /** Manual full re-initialisation. */
  refresh: () => void;

  /** Clear ended meeting state and return to the "No Active Meeting" view. */
  clearEndedMeeting: () => void;

  /**
   * Immediately terminate an utterance: remove from interimMap and mark
   * terminal so late interims for this utterance_id are ignored.
   * Called locally (Cancel / Stop timeout) without waiting for the
   * backend WebSocket event. Does NOT broadcast or write to the database.
   */
  terminateUtterance: (utteranceId: string) => void;
}

// ── Internal state ──────────────────────────────────────────────────────────

interface DataState {
  meeting: Meeting | null;
  seats: SeatDisplay[];
  speakerSeatId: number | null;
  attendees: Attendee[];
  agenda: Agenda[];
  activeVote: VoteStatistics | null;
  voteResults: VoteStatistics[];
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
  voteResults: [],
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
  const [interimMap, setInterimMap] = useState<Record<string, InterimTranslation>>({});

  // ── Ended meeting state ──────────────────────────────────────────────────
  // We keep ended-meeting info in refs (stable across renders) so the stable
  // doFetch callback can read them without deps.  The React state only drives
  // conditional rendering in the UI.
  const endedMeetingIdRef = useRef<number | null>(null);
  const endedMeetingTitleRef = useRef<string | null>(null);
  const [isEndedMeeting, setIsEndedMeeting] = useState<boolean>(() => {
    try {
      const saved = sessionStorage.getItem('endedMeetingId');
      if (saved) {
        const parsed = Number(saved);
        if (!isNaN(parsed)) {
          endedMeetingIdRef.current = parsed;
          endedMeetingTitleRef.current = sessionStorage.getItem('endedMeetingTitle');
          return true;
        }
      }
    } catch { /* sessionStorage may not be available */ }
    return false;
  });

  // Track if a refresh is in flight to avoid races
  const fetchingRef = useRef(false);
  // Track if a refresh was requested while one was already in flight
  const needsRefreshRef = useRef(false);
  // Track effective meeting ID for agenda_updated filtering
  const effectiveMeetingIdRef = useRef<number | null>(null);

  // ── Task 126: terminal utterance ID tracking ──────────────────────────
  // Prevents late translation_interim from re-creating live caption after
  // a translation_final or translation_interim_cancelled for the same
  // utterance_id. Uses Map<utteranceId, timestamp>; keeps last 200 entries.
  const terminalUtteranceIdsRef = useRef<Map<string, number>>(new Map());
  const MAX_TERMINAL_IDS = 200;

  const recordTerminalId = useCallback((uid: string) => {
    const map = terminalUtteranceIdsRef.current;
    map.set(uid, Date.now());
    // Trim oldest entry when over capacity (Map iterates in insertion order)
    if (map.size > MAX_TERMINAL_IDS) {
      const firstKey = map.keys().next().value;
      if (firstKey !== undefined) map.delete(firstKey);
    }
  }, []);

  // ── Task 127A: local utterance termination (Cancel / Stop timeout) ────
  // Immediately removes the utterance from interimMap and marks it terminal
  // so late interims don't re-create live caption. Does NOT broadcast.
  const terminateUtterance = useCallback((utteranceId: string) => {
    if (!utteranceId) return;
    recordTerminalId(utteranceId);
    setInterimMap((prev) => {
      if (!(utteranceId in prev)) return prev;
      const next = { ...prev };
      delete next[utteranceId];
      trace("interim_removed_at", { utteranceId, reason: "local_cleanup" });
      return next;
    });
  }, [recordTerminalId]);

  // ── Core fetch function ────────────────────────────────────────────────

  const doFetch = useCallback(async (isInitial: boolean) => {
    // If already fetching, mark that a re-fetch is needed and return.
    // The in-flight fetch will check this flag and re-trigger itself.
    if (fetchingRef.current) {
      needsRefreshRef.current = true;
      return;
    }
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

      // ── Determine effective meeting (active or ended) ──────────────────
      let isEnded = false;

      if (meeting) {
        // Active meeting found — clear any lingering ended-meeting state
        if (endedMeetingIdRef.current != null) {
          endedMeetingIdRef.current = null;
          endedMeetingTitleRef.current = null;
          setIsEndedMeeting(false);
          try {
            sessionStorage.removeItem('endedMeetingId');
            sessionStorage.removeItem('endedMeetingTitle');
          } catch { /* sessionStorage may throw */ }
        }
      } else if (endedMeetingIdRef.current == null) {
        // No active meeting and no ref yet — try sessionStorage (AdminDashboard
        // may have written it before calling refresh() after endMeeting).
        try {
          const saved = sessionStorage.getItem('endedMeetingId');
          if (saved) {
            const parsed = Number(saved);
            if (!isNaN(parsed)) {
              endedMeetingIdRef.current = parsed;
              endedMeetingTitleRef.current = sessionStorage.getItem('endedMeetingTitle');
              setIsEndedMeeting(true);
            }
          }
        } catch { /* sessionStorage may throw */ }
      }

      isEnded = !meeting && endedMeetingIdRef.current != null;
      const effectiveMeeting: Meeting | null = meeting ?? (
        endedMeetingIdRef.current != null
          ? {
              id: endedMeetingIdRef.current,
              title: endedMeetingTitleRef.current ?? '',
              description: null,
              status: 'finished' as const,
              created_at: '',
              started_at: null,
              ended_at: null,
            }
          : null
      );
      const effectiveMeetingId = effectiveMeeting?.id ?? null;
      effectiveMeetingIdRef.current = effectiveMeetingId;

      const voteExists = rawActiveVote != null && !isEnded;
      setHasActiveVote(voteExists);

      // Step 2: Meeting-dependent resources
      let attendees: Attendee[] = [];
      let agenda: Agenda[] = [];
      let serviceCalls: ServiceCall[] = [];
      let translations: TranslationRecord[] = [];
      let voteResults: VoteStatistics[] = [];

      if (effectiveMeetingId) {
        const [a, ag, sc, tr, vr] = await Promise.all([
          fetchAttendees(effectiveMeetingId),
          fetchAgendas(effectiveMeetingId),
          fetchServiceCalls(effectiveMeetingId),
          fetchTranslations(effectiveMeetingId),
          fetchVoteResultsForMeeting(effectiveMeetingId),
        ]);
        attendees = a;
        agenda = ag;
        serviceCalls = sc;
        translations = tr.entries;
        voteResults = vr;
      }

      // Step 3: Vote statistics (if active vote)
      let voteStats: VoteStatistics | null = null;
      if (rawActiveVote && !isEnded) {
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
        meeting: effectiveMeeting,
        seats,
        speakerSeatId: speaker.seat_id,
        attendees,
        agenda,
        activeVote: voteStats,
        voteResults,
        serviceCalls,
        translations,
      });

      // Update WebSocket meeting target (null for ended meetings — no WS needed)
      setConnectMeetingId(isEnded ? null : effectiveMeetingId);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "An unknown error occurred";
      setError(msg);
    } finally {
      fetchingRef.current = false;
      setLoading(false);
      // If a refresh was queued while we were fetching, re-trigger now.
      if (needsRefreshRef.current) {
        needsRefreshRef.current = false;
        doFetch(false);
      }
    }
  }, []);

  // ── Initial load ───────────────────────────────────────────────────────

  useEffect(() => {
    doFetch(true);
  }, [doFetch]);

  // ── WebSocket event handler ────────────────────────────────────────────

  const handleWSEvent = useCallback(
    (event: string, message: WSMessage) => {
      // translation_interim: update interimMap only, no HTTP refresh
      if (event === "translation_interim") {
        const p = message.payload;
        const uid = p.utterance_id as string;
        if (!uid) return;
        const revision = p.revision as number;

        // Task 126: skip late interim for already-terminal utterance_id
        if (terminalUtteranceIdsRef.current.has(uid)) {
          trace("frontend_interim_skipped_at", {
            utteranceId: uid,
            revision,
            reason: "utterance_terminal",
          });
          return;
        }

        trace("frontend_interim_received_at", {
          utteranceId: uid,
          revision,
          seatId: p.seat_id,
        });

        setInterimMap((prev) => {
          const existing = prev[uid];
          // Only accept equal or higher revision (protect against stale frames)
          if (existing && existing.revision > revision) return prev;

          // Extract optional caption from payload
          const rawCaption = p.caption;
          let caption: InterimTranslation['caption'] | undefined;
          if (rawCaption && typeof rawCaption === 'object') {
            const cap = rawCaption as Record<string, unknown>;
            caption = {
              previousLine: String(cap.previous_line ?? ''),
              currentLine: String(cap.current_line ?? ''),
              mode: String(cap.mode ?? 'two_line'),
            };
          }

          return {
            ...prev,
            [uid]: {
              utteranceId: uid,
              seatId: p.seat_id as number,
              revision,
              sourceLang: p.source_lang as string,
              targetLang: p.target_lang as string,
              sourceText: p.source_text as string,
              translatedText: p.translated_text as string,
              caption,
            },
          };
        });
        return;
      }

      // translation_interim_cancelled: remove matching interim, no HTTP refresh
      if (event === "translation_interim_cancelled") {
        const uid = message.payload.utterance_id as string;
        if (!uid) return;
        // Task 126: mark as terminal and skip if already recorded
        if (terminalUtteranceIdsRef.current.has(uid)) return;
        recordTerminalId(uid);
        trace("frontend_cancel_received_at", { utteranceId: uid, reason: message.payload.reason });
        setInterimMap((prev) => {
          if (!(uid in prev)) return prev;
          const next = { ...prev };
          delete next[uid];
          trace("interim_removed_at", { utteranceId: uid, reason: "cancelled" });
          return next;
        });
        return;
      }

      // translation_final: remove interim, then refresh translations via full re-fetch
      if (event === "translation_final") {
        const uid = message.payload.utterance_id as string;
        trace("frontend_final_received_at", { utteranceId: uid ?? undefined, translationId: message.payload.translation_id });
        if (uid) {
          // Task 126: mark as terminal (skip if already recorded)
          if (!terminalUtteranceIdsRef.current.has(uid)) {
            recordTerminalId(uid);
          }
          setInterimMap((prev) => {
            if (!(uid in prev)) return prev;
            const next = { ...prev };
            delete next[uid];
            trace("interim_removed_at", { utteranceId: uid, reason: "final" });
            return next;
          });
        }
        // Full refresh to pick up the new persisted final record
        doFetch(false);
        return;
      }

      // agenda_updated: only refresh if meeting_id matches current meeting
      if (event === "agenda_updated") {
        if (message.meeting_id !== effectiveMeetingIdRef.current) return;
        doFetch(false);
        return;
      }

      // All other events: full HTTP refresh (existing behaviour)
      doFetch(false);
    },
    [doFetch, recordTerminalId],
  );

  const connection = useWebSocket(connectMeetingId, handleWSEvent);

  // ── Clear ended meeting ──────────────────────────────────────────────

  const clearEndedMeeting = useCallback(() => {
    endedMeetingIdRef.current = null;
    endedMeetingTitleRef.current = null;
    setIsEndedMeeting(false);
    setData(EMPTY_DATA);
    try {
      sessionStorage.removeItem('endedMeetingId');
      sessionStorage.removeItem('endedMeetingTitle');
      } catch { /* sessionStorage may throw */ }
  }, []);

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
    voteResults: data.voteResults,
    hasActiveVote,
    voteStatsError,
    serviceCalls: data.serviceCalls,
    translations: data.translations,
    interimMap,
    connection,
    noMeeting: !loading && !data.meeting && !error && !isEndedMeeting,
    isEndedMeeting,
    refresh: () => doFetch(false),
    clearEndedMeeting,
    terminateUtterance,
  };
}
