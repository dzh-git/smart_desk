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
// WebSocket event handling:
//   translation_interim           → update interimMap only, no HTTP refresh
//   translation_final             → remove matching interim, full HTTP refresh
//   translation_interim_cancelled → remove matching interim, no HTTP refresh
//   all other events              → full HTTP refresh (existing behaviour)
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
  fetchVoteResultsForMeeting,
  fetchAgendas,
  fetchAttendees,
  fetchCurrentServiceCall,
  fetchTranslations,
} from "../api/resources";
import { buildSeatDisplays } from "../api/adapters";
import { useWebSocket } from "./useWebSocket";
import type { WSMessage } from "./useWebSocket";
import { trace } from "../audio/speechTrace";
import type {
  ConnectionStatus,
  SeatDisplay,
  InterimTranslation,
  LiveLyricSentence,
  PendingTranslation,
} from "../types";
import {
  removeLyricsForUtterance,
  upsertLiveLyric,
  type LiveLyricMap,
} from "./liveLyrics";
import type {
  Meeting,
  Attendee,
  Agenda,
  Vote,
  VoteStatistics,
  ServiceCall,
  TranslationRecord,
} from "../api/types";

type LiveCaption = NonNullable<InterimTranslation["caption"]>;
type CaptionCarry = { oldUtteranceId: string; caption?: LiveCaption };

function parseLiveCaption(value: unknown): LiveCaption | undefined {
  if (!value || typeof value !== "object") return undefined;
  const caption = value as Record<string, unknown>;
  return {
    previousLine: String(caption.previous_line ?? ""),
    currentLine: String(caption.current_line ?? ""),
    mode: String(caption.mode ?? "two_line"),
  };
}

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
  /** Vote statistics for current and historical meeting votes, newest first. */
  voteResults: VoteStatistics[];
  /** True when vote statistics fetch failed. */
  voteStatsError: string | null;
  /** Current pending service call for this seat, or null. */
  currentServiceCall: ServiceCall | null;
  /** Translation history (empty when no meeting). */
  translations: TranslationRecord[];
  /** Most recent sentence-final bilingual subtitle for the live panel. */
  liveFinal: TranslationRecord | null;
  /** Interim translations keyed by utterance_id (not persisted). */
  interimMap: Record<string, InterimTranslation>;
  /** Meeting lyric history per seat; the viewport scrolls older pairs. */
  lyricMap: LiveLyricMap;
  /** Auto-finalized text waiting for background translation/persistence. */
  pendingFinalMap: Record<string, PendingTranslation>;
  /** WebSocket connection status. */
  connection: ConnectionStatus;
  /** True when there is no active meeting (idle/waiting state). */
  noMeeting: boolean;

  /** Manual full re-initialisation. */
  refresh: () => void;

  /**
   * Immediately terminate an utterance: remove from interimMap and mark
   * terminal so late interims for this utterance_id are ignored.
   * Called locally (Cancel / Stop timeout) without waiting for the
   * backend WebSocket event. Does NOT broadcast or write to the database.
   */
  terminateUtterance: (utteranceId: string, reason?: string) => void;
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
  voteResults: VoteStatistics[];
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
  voteResults: [],
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
  const [interimMap, setInterimMap] = useState<Record<string, InterimTranslation>>({});
  const [lyricMap, setLyricMap] = useState<LiveLyricMap>({});
  const [pendingFinalMap, setPendingFinalMap] = useState<Record<string, PendingTranslation>>({});
  const [liveFinal, setLiveFinal] = useState<TranslationRecord | null>(null);

  // Track if a refresh is in flight to avoid races
  const fetchingRef = useRef(false);
  // Track if a refresh was requested while one was already in flight
  const needsRefreshRef = useRef(false);

  // ── Task 126: terminal utterance ID tracking ──────────────────────────
  // Prevents late translation_interim from re-creating live caption after
  // a translation_final or translation_interim_cancelled for the same
  // utterance_id. Uses Map<utteranceId, timestamp>; keeps last 200 entries.
  const terminalUtteranceIdsRef = useRef<Map<string, number>>(new Map());
  const finalizingUtteranceIdsRef = useRef<Set<string>>(new Set());
  const finalizedUtteranceIdsRef = useRef<Set<string>>(new Set());
  const cancelledUtteranceIdsRef = useRef<Set<string>>(new Set());
  const captionCarryByNextIdRef = useRef<Map<string, CaptionCarry>>(new Map());
  const captionCarryBySeatRef = useRef<Map<number, CaptionCarry>>(new Map());
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

  const resetInterimEpoch = useCallback(() => {
    terminalUtteranceIdsRef.current.clear();
    finalizingUtteranceIdsRef.current.clear();
    finalizedUtteranceIdsRef.current.clear();
    cancelledUtteranceIdsRef.current.clear();
    captionCarryByNextIdRef.current.clear();
    captionCarryBySeatRef.current.clear();
    setInterimMap({});
    setLyricMap({});
    setPendingFinalMap({});
    setLiveFinal(null);
  }, []);

  useEffect(() => {
    resetInterimEpoch();
  }, [connectMeetingId, resetInterimEpoch]);

  // ── Task 127A: local utterance termination (Cancel / Stop timeout) ────
  // Immediately removes the utterance from interimMap and marks it terminal
  // so late interims don't re-create live caption. Does NOT broadcast.
  const terminateUtterance = useCallback((utteranceId: string, reason = "cancel") => {
    if (!utteranceId) return;
    recordTerminalId(utteranceId);
    if (reason === "cancel") {
      cancelledUtteranceIdsRef.current.add(utteranceId);
    }
    captionCarryByNextIdRef.current.delete(utteranceId);
    for (const [seat, carry] of captionCarryBySeatRef.current) {
      if (carry.oldUtteranceId === utteranceId) {
        captionCarryBySeatRef.current.delete(seat);
      }
    }
    setInterimMap((prev) => {
      if (!(utteranceId in prev)) return prev;
      const next = { ...prev };
      delete next[utteranceId];
      trace("interim_removed_at", { utteranceId, reason: "local_cleanup" });
      return next;
    });
    if (reason === "cancel") {
      setLyricMap((prev) => removeLyricsForUtterance(prev, utteranceId));
    }
    setPendingFinalMap((prev) => {
      if (!(utteranceId in prev)) return prev;
      const next = { ...prev };
      delete next[utteranceId];
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

      const meetingId = meeting?.id ?? null;

      // Step 2: Meeting-dependent resources
      let attendees: Attendee[] = [];
      let agenda: Agenda[] = [];
      let currentServiceCall: ServiceCall | null = null;
      let translations: TranslationRecord[] = [];
      let voteResults: VoteStatistics[] = [];

      if (meetingId) {
        // Fetch attendees, agendas, and translations in parallel (no duplicates)
        const [a, ag, tr, vr] = await Promise.all([
          fetchAttendees(meetingId),
          fetchAgendas(meetingId),
          fetchTranslations(meetingId).then((r) => r.entries),
          fetchVoteResultsForMeeting(meetingId, rawActiveVote?.id),
        ]);
        attendees = a;
        agenda = ag;
        translations = tr;
        voteResults = vr;

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
        voteResults,
        currentServiceCall,
        translations,
      });
      const finalizedIds = new Set(
        translations
          .map((entry) => entry.utterance_id)
          .filter((uid): uid is string => Boolean(uid)),
      );
      if (finalizedIds.size) {
        setPendingFinalMap((prev) => {
          const next = { ...prev };
          let changed = false;
          for (const uid of finalizedIds) {
            if (uid in next) {
              delete next[uid];
              changed = true;
            }
          }
          return changed ? next : prev;
        });
      }

      // Update WebSocket meeting target
      setConnectMeetingId(meetingId);
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
  }, [seatId]);

  // ── Initial load ───────────────────────────────────────────────────────

  useEffect(() => {
    doFetch(true);
  }, [doFetch]);

  const hasMeeting = data.meeting != null;
  useEffect(() => {
    if (loading || (hasMeeting && !error)) return;
    const timer = window.setInterval(() => void doFetch(false), 5000);
    return () => window.clearInterval(timer);
  }, [doFetch, error, hasMeeting, loading]);

  const refresh = useCallback(() => doFetch(false), [doFetch]);

  // ── WebSocket event handler ────────────────────────────────────────────

  const handleWSEvent = useCallback(
    (event: string, message: WSMessage) => {
      if (event === "reconnected") {
        resetInterimEpoch();
        doFetch(false);
        return;
      }

      if (event === "translation_sentence") {
        const p = message.payload;
        const uid = String(p.utterance_id ?? "");
        const sentenceId = String(p.sentence_id ?? "");
        const seat = Number(p.seat_id);
        if (
          !uid
          || !sentenceId
          || !Number.isFinite(seat)
          || cancelledUtteranceIdsRef.current.has(uid)
        ) return;
        const status = String(p.translation_status ?? "pending");
        trace(
          status === "pending"
            ? "frontend_sentence_pending_received_at"
            : "frontend_sentence_translation_received_at",
          {
          utteranceId: uid,
          sentenceId,
          sentenceSequence: Number(p.sentence_sequence ?? 0),
          revision: Number(p.revision ?? 0),
          seatId: seat,
          translationStatus: status,
          },
        );
        const lyric: LiveLyricSentence = {
          utteranceId: uid,
          sentenceId,
          sentenceSequence: Number(p.sentence_sequence ?? 0),
          seatId: seat,
          revision: Number(p.revision ?? 0),
          sourceLang: String(p.source_lang ?? "unknown"),
          targetLang: String(p.target_lang ?? "unknown"),
          sourceText: String(p.source_text ?? ""),
          translatedText: String(p.translated_text ?? ""),
          translationStatus: status === "ok"
            ? "ok"
            : status === "unavailable"
              ? "unavailable"
              : "pending",
          translationError: p.translation_error
            ? String(p.translation_error)
            : undefined,
          recognitionStatus: p.recognition_status === "correcting"
            ? "correcting"
            : p.recognition_status === "degraded" ? "degraded" : "ok",
          sourceLocked: p.source_locked === true,
        };
        setLyricMap((prev) => upsertLiveLyric(prev, lyric));
        return;
      }

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
        setLiveFinal(null);

        const seat = p.seat_id as number;
        const sentenceId = String(p.sentence_id ?? "");
        const sentenceSourceText = String(p.sentence_source_text ?? "");
        if (sentenceId && sentenceSourceText) {
          const sentenceState = String(p.sentence_state ?? "forming");
          setLyricMap((prev) => upsertLiveLyric(prev, {
            utteranceId: uid,
            sentenceId,
            sentenceSequence: Number(p.sentence_sequence ?? 0),
            seatId: seat,
            revision: Number(revision ?? 0),
            sourceLang: String(p.source_lang ?? "unknown"),
            targetLang: String(p.target_lang ?? "unknown"),
            sourceText: sentenceSourceText,
            translatedText: "",
            translationStatus: sentenceState === "completed" ? "pending" : "forming",
          }));
        }
        const carry = captionCarryByNextIdRef.current.get(uid)
          ?? captionCarryBySeatRef.current.get(seat);
        const fallbackCarry = captionCarryBySeatRef.current.get(seat);

        setInterimMap((prev) => {
          const existing = prev[uid];
          if (p.translation_only === true && existing) {
            const translationRevision = Number(p.translation_revision ?? revision);
            const translationSourceText = String(
              p.translation_source_text ?? p.source_text ?? "",
            );
            if (
              existing.translationSourceText
              && existing.translationSourceText !== translationSourceText
            ) return prev;
            if ((existing.translationRevision ?? -1) > translationRevision) return prev;
            return {
              ...prev,
              [uid]: {
                ...existing,
                sourceLang: String(p.source_lang ?? existing.sourceLang),
                targetLang: String(p.target_lang ?? existing.targetLang),
                translatedText: String(p.translated_text ?? ""),
                translationSourceText,
                translationRevision,
              },
            };
          }

          // Only source-caption events reject an older recognition revision.
          // A translated prefix may legitimately trail the newest source.
          if (existing && existing.revision > revision) return prev;

          // Extract optional caption from payload
          let caption = parseLiveCaption(p.caption);
          const hasOwnPreviousLine = Boolean(caption?.previousLine);
          if (caption && carry?.caption && !hasOwnPreviousLine) {
            caption = {
              ...caption,
              previousLine:
                carry.caption.currentLine || carry.caption.previousLine,
            };
          }

          const next = { ...prev };
          const translationSourceText = String(
            p.translation_source_text ?? p.source_text ?? "",
          );
          const sameTranslationWindow =
            existing?.translationSourceText === translationSourceText;
          // A seat can own only one live speech session.  When the speech
          // socket reconnects, keep the old caption visible until the first
          // new interim arrives, then replace it atomically by seat.
          for (const [existingUid, interim] of Object.entries(next)) {
            if (existingUid !== uid && interim.seatId === seat) {
              delete next[existingUid];
            }
          }
          if (fallbackCarry && fallbackCarry.oldUtteranceId !== uid) {
            delete next[fallbackCarry.oldUtteranceId];
          }
          next[uid] = {
              utteranceId: uid,
              seatId: seat,
              revision,
              sourceLang: p.source_lang as string,
              targetLang: p.target_lang as string,
              sourceText: p.source_text as string,
              translatedText: String(p.translated_text ?? "")
                || (sameTranslationWindow ? existing?.translatedText : "")
                || "",
              requestedLanguage: String(p.requested_language ?? "auto") as "auto" | "zh" | "en",
              detectedLanguage: String(p.detected_language ?? p.source_lang ?? "unknown") as "unknown" | "zh" | "en",
              recognitionEngine: String(p.recognition_engine ?? "unknown") as "unknown" | "paraformer_streaming" | "sherpa_onnx_streaming" | "sensevoice_rolling_fallback",
              translationSourceText,
              translationRevision: sameTranslationWindow
                ? existing?.translationRevision
                : undefined,
              caption,
            };
          return next;
        });
        if (carry && parseLiveCaption(p.caption)?.previousLine) {
          captionCarryByNextIdRef.current.delete(uid);
          captionCarryBySeatRef.current.delete(seat);
        }

        trace("frontend_interim_rendered_at", {
          utteranceId: uid,
          revision,
          seatId: p.seat_id as number,
        });
        return;
      }

      if (event === "translation_finalizing") {
        const p = message.payload;
        const uid = p.utterance_id as string;
        if (!uid || finalizingUtteranceIdsRef.current.has(uid)) return;
        finalizingUtteranceIdsRef.current.add(uid);
        recordTerminalId(uid);
        captionCarryByNextIdRef.current.delete(uid);
        const seat = p.seat_id as number;
        const nextUid = p.next_utterance_id as string | undefined;
        const payloadCaption = parseLiveCaption(p.caption);
        const payloadCarry = { oldUtteranceId: uid, caption: payloadCaption };
        if (nextUid) {
          captionCarryByNextIdRef.current.set(nextUid, payloadCarry);
        } else {
          captionCarryBySeatRef.current.set(seat, payloadCarry);
        }
        setInterimMap((prev) => {
          const oldInterim = prev[uid];
          const caption = payloadCaption ?? oldInterim?.caption;
          const carry = { oldUtteranceId: uid, caption };
          const next = { ...prev };
          if (nextUid) {
            delete next[uid];
            captionCarryByNextIdRef.current.set(nextUid, carry);
            next[nextUid] = {
              utteranceId: nextUid,
              seatId: seat,
              revision: 0,
              sourceLang: String(p.source_lang ?? "zh"),
              targetLang: String(p.target_lang ?? "en"),
              sourceText: String(p.source_text ?? oldInterim?.sourceText ?? ""),
              translatedText: oldInterim?.translatedText ?? "",
              translationSourceText: oldInterim?.translationSourceText,
              translationRevision: oldInterim?.translationRevision,
              caption,
            };
          } else {
            captionCarryBySeatRef.current.set(seat, carry);
          }
          return next;
        });
        if (!finalizedUtteranceIdsRef.current.has(uid)) {
          setPendingFinalMap((prev) => ({
            ...prev,
            [uid]: {
              utteranceId: uid,
              seatId: seat,
              sourceLang: p.source_lang as string,
              targetLang: p.target_lang as string,
              sourceText: p.source_text as string,
              boundaryReason: p.boundary_reason as string,
            },
          }));
        }
        return;
      }

      // translation_interim_cancelled: remove matching interim, no HTTP refresh
      if (event === "translation_interim_cancelled") {
        const uid = message.payload.utterance_id as string;
        if (!uid) return;
        captionCarryByNextIdRef.current.delete(uid);
        for (const [seat, carry] of captionCarryBySeatRef.current) {
          if (carry.oldUtteranceId === uid) {
            captionCarryBySeatRef.current.delete(seat);
          }
        }
        if (!terminalUtteranceIdsRef.current.has(uid)) recordTerminalId(uid);
        cancelledUtteranceIdsRef.current.add(uid);
        trace("frontend_cancel_received_at", { utteranceId: uid, reason: message.payload.reason });
        setInterimMap((prev) => {
          if (!(uid in prev)) return prev;
          const next = { ...prev };
          delete next[uid];
          trace("interim_removed_at", { utteranceId: uid, reason: "cancelled" });
          return next;
        });
        setLyricMap((prev) => removeLyricsForUtterance(prev, uid));
        setPendingFinalMap((prev) => {
          if (!(uid in prev)) return prev;
          const next = { ...prev };
          delete next[uid];
          return next;
        });
        return;
      }

      // translation_final: remove interim, then refresh translations via full re-fetch
      if (event === "translation_final") {
        const p = message.payload;
        const uid = p.utterance_id as string;
        const carriedNextUids: string[] = [];
        for (const [nextUid, carry] of captionCarryByNextIdRef.current) {
          if (carry.oldUtteranceId === uid) {
            carriedNextUids.push(nextUid);
            captionCarryByNextIdRef.current.delete(nextUid);
          }
        }
        for (const [seat, carry] of captionCarryBySeatRef.current) {
          if (carry.oldUtteranceId === uid) {
            captionCarryBySeatRef.current.delete(seat);
          }
        }
        trace("frontend_final_received_at", { utteranceId: uid ?? undefined, translationId: p.translation_id });
        setLiveFinal({
          id: Number(p.translation_id),
          meeting_id: Number(message.meeting_id),
          seat_id: Number(p.seat_id),
          utterance_id: uid || null,
          source_lang: String(p.source_lang ?? "unknown"),
          target_lang: String(p.target_lang ?? "unknown"),
          source_text: String(p.source_text ?? ""),
          translated_text: String(p.translated_text ?? ""),
          translation_status: p.translation_status === "unavailable" ? "unavailable" : "ok",
          translation_error: p.translation_error ? String(p.translation_error) : null,
          created_at: new Date().toISOString(),
          source_type: p.source_type ? String(p.source_type) : "speech_ws",
        });
        if (uid) {
          finalizedUtteranceIdsRef.current.add(uid);
          setLyricMap((prev) => removeLyricsForUtterance(prev, uid));
          // Task 126: mark as terminal (skip if already recorded)
          if (!terminalUtteranceIdsRef.current.has(uid)) {
            recordTerminalId(uid);
          }
          setInterimMap((prev) => {
            const next = { ...prev };
            let changed = false;
            if (uid in next) {
              delete next[uid];
              changed = true;
            }
            for (const nextUid of carriedNextUids) {
              if (next[nextUid]?.revision === 0) {
                delete next[nextUid];
                changed = true;
              }
            }
            if (!changed) return prev;
            trace("interim_removed_at", { utteranceId: uid, reason: "final" });
            return next;
          });
        }
        // Full refresh to pick up the new persisted final record
        doFetch(false);
        return;
      }

      // All other events: full HTTP refresh (existing behaviour)
      doFetch(false);
    },
    [doFetch, recordTerminalId, resetInterimEpoch],
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
    voteResults: data.voteResults,
    voteStatsError,
    currentServiceCall: data.currentServiceCall,
    translations: data.translations,
    liveFinal,
    interimMap,
    lyricMap,
    pendingFinalMap,
    connection,
    noMeeting: !loading && !data.meeting && !error,
    refresh,
    terminateUtterance,
  };
}
