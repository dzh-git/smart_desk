import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Monitor, RefreshCw, Vote as VoteIcon } from "lucide-react";
import {
  fetchActiveMeeting,
  fetchActiveVote,
  fetchVoteResultsForMeeting,
  fetchVoteStatistics,
} from "../api/resources";
import { useWebSocket } from "../hooks/useWebSocket";
import type { WSMessage } from "../hooks/useWebSocket";
import type { Meeting, VoteStatistics } from "../api/types";

const STORAGE_KEY = "smartdesk.display.endedMeetingId";

/** Polling interval for detecting a new active meeting (ms).
 *  Can be overridden for testing via __setPollInterval. */
export let DISPLAY_POLL_INTERVAL_MS = 7000;

/** Testing hook — allow tests to override the interval. */
export function __setPollInterval(ms: number) {
  DISPLAY_POLL_INTERVAL_MS = ms;
}

interface DisplayState {
  loading: boolean;
  error: string | null;
  meeting: Meeting | null;
  activeVote: VoteStatistics | null;
  voteResults: VoteStatistics[];
  currentMeetingId: number | null;
  endedMeetingId: number | null;
}

const EMPTY_STATE: DisplayState = {
  loading: true,
  error: null,
  meeting: null,
  activeVote: null,
  voteResults: [],
  currentMeetingId: null,
  endedMeetingId: null,
};

/** Derive the effective meeting ID for fetching data. */
function getEffectiveMeetingId(
  meeting: Meeting | null,
  endedMeetingId: number | null,
): number | null {
  if (meeting) return meeting.id;
  if (endedMeetingId !== null) return endedMeetingId;
  return null;
}

/** Determine whether we are showing an ended meeting. */
function getIsEndedMeeting(
  meeting: Meeting | null,
  endedMeetingId: number | null,
): boolean {
  return !meeting && endedMeetingId !== null;
}

export function DisplayView() {
  const [state, setState] = useState<DisplayState>(() => {
    // Restore endedMeetingId from sessionStorage on initial load
    const stored = tryGetStoredEndedId();
    return { ...EMPTY_STATE, endedMeetingId: stored };
  });

  // Track endedMeetingId in a ref so the load callback can access the latest value
  // without re-creating itself or reading from state synchronously.
  const endedMeetingIdRef = useRef<number | null>(state.endedMeetingId);

  // Keep ref in sync with state
  useEffect(() => {
    endedMeetingIdRef.current = state.endedMeetingId;
  }, [state.endedMeetingId]);

  // Track the last active meeting id so we can save it on meeting_ended
  const lastActiveMeetingIdRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const meeting = await fetchActiveMeeting();
      const endedMeetingId = endedMeetingIdRef.current;

      // If an active meeting exists, prefer it and discard any stored ended id
      if (meeting) {
        clearStoredEndedId();
        const [rawActiveVote, voteResults] = await Promise.all([
          fetchActiveVote(),
          fetchVoteResultsForMeeting(meeting.id),
        ]);
        const activeVote = rawActiveVote
          ? await fetchVoteStatistics(rawActiveVote.id)
          : null;

        lastActiveMeetingIdRef.current = meeting.id;
        setState({
          loading: false,
          error: null,
          meeting,
          activeVote,
          voteResults,
          currentMeetingId: meeting.id,
          endedMeetingId: null,
        });
        return;
      }

      // No active meeting — check if we have an ended meeting to show
      if (endedMeetingId !== null) {
        const voteResults = await fetchVoteResultsForMeeting(endedMeetingId);
        setState({
          loading: false,
          error: null,
          meeting: null,
          activeVote: null,
          voteResults,
          currentMeetingId: null,
          endedMeetingId,
        });
        return;
      }

      // No active meeting and no ended meeting — empty state
      setState({
        loading: false,
        error: null,
        meeting: null,
        activeVote: null,
        voteResults: [],
        currentMeetingId: null,
        endedMeetingId: null,
      });
    } catch (err) {
      setState((prev) => ({
        ...prev,
        loading: false,
        error: err instanceof Error ? err.message : "Failed to load display",
      }));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // ── Poll for active meeting when in waiting state ────────────────────────
  // When DisplayView has no active meeting and no ended meeting id, poll
  // the backend every POLL_INTERVAL_MS to detect a newly started meeting.
  // The timer is cleaned up when a meeting is found, when ended meeting
  // results are displayed, or on unmount.
  useEffect(() => {
    // Poll when there is no active meeting (includes both waiting state and
    // ended-meeting result view). If poll finds a new active meeting, it
    // calls load() which switches to it and clears the endedMeetingId.
    // When no active meeting exists, the ended results remain intact.
    const shouldPoll =
      !state.loading &&
      !state.meeting &&
      !state.error;

    if (!shouldPoll) return;

    const pollTimer = setInterval(async () => {
      try {
        const meeting = await fetchActiveMeeting();
        if (meeting) {
          // New active meeting found — update state and stop polling
          clearInterval(pollTimer);
          // Persist: store endedMeetingId to prevent re-polling on re-render
          // that triggers a new effect scheduling.  The load() call below
          // will see the active meeting and clear any stored ended id.
          load();
        }
      } catch {
        // Silently ignore polling errors — the manual Refresh button exists.
      }
    }, DISPLAY_POLL_INTERVAL_MS);

    return () => {
      clearInterval(pollTimer);
    };
  }, [state.loading, state.meeting, state.error, load]);

  const handleEvent = useCallback(
    (event: string, message: WSMessage) => {
      if (
        event === "vote_started" ||
        event === "vote_updated" ||
        event === "vote_closed" ||
        event === "meeting_ended"
      ) {
        // For meeting_ended, save the meeting id so we keep showing vote
        // results even after the active meeting is gone.
        if (event === "meeting_ended") {
          // Prefer the meeting_id from the WS message payload; fall back to
          // the ref so we still work if the message lacks a valid id.
          const meetingId =
            typeof message.meeting_id === "number" && message.meeting_id > 0
              ? message.meeting_id
              : lastActiveMeetingIdRef.current;

          if (meetingId !== null) {
            persistEndedId(meetingId);
            setState((prev) => ({
              ...prev,
              endedMeetingId: meetingId,
              currentMeetingId: null,
            }));
            endedMeetingIdRef.current = meetingId;
          }
        }
        load();
      }
    },
    [load],
  );

  const effectiveMeetingId = getEffectiveMeetingId(
    state.meeting,
    state.endedMeetingId,
  );
  const isEndedMeeting = getIsEndedMeeting(state.meeting, state.endedMeetingId);

  useWebSocket(effectiveMeetingId, handleEvent, 0);

  const displayVote =
    state.activeVote ??
    state.voteResults.find((vote) => vote.status === "closed") ??
    null;

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 px-8 py-6">
        <div className="flex min-w-0 items-center gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-slate-700 bg-slate-900">
            <Monitor size={24} className="text-sky-400" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">
              SmartDesk Display
            </p>
            <h1 className="truncate text-2xl font-bold">
              {isEndedMeeting
                ? "Meeting Ended"
                : state.meeting?.title ?? "Waiting for Meeting"}
            </h1>
          </div>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-900"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-8 py-10">
        {state.loading && (
          <div className="flex items-center justify-center gap-3 rounded-3xl border border-slate-800 bg-slate-900/60 p-12 text-slate-300">
            <Loader2 size={22} className="animate-spin" />
            Loading display...
          </div>
        )}

        {state.error && (
          <div className="rounded-3xl border border-rose-800 bg-rose-950/40 p-8 text-rose-200">
            {state.error}
          </div>
        )}

        {isEndedMeeting && !state.loading && !state.error && (
          <div className="rounded-3xl border border-amber-800 bg-amber-950/40 p-6 text-center">
            <p className="text-lg font-semibold text-amber-300">
              This meeting has ended. Results are preserved below.
            </p>
          </div>
        )}

        {!state.loading && !state.error && !displayVote && (
          <div className="flex flex-col items-center justify-center rounded-3xl border border-slate-800 bg-slate-900/60 p-12 text-center">
            <VoteIcon size={36} className="mb-4 text-slate-500" />
            <p className="text-2xl font-bold">No votes yet</p>
            <p className="mt-2 text-sm text-slate-400">
              Voting results will appear here during or after a vote.
            </p>
          </div>
        )}

        {!state.loading && !state.error && displayVote && (
          <DisplayVoteResult vote={displayVote} />
        )}
      </main>
    </div>
  );
}

// ── sessionStorage helpers ─────────────────────────────────────────────────────

function tryGetStoredEndedId(): number | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw === null) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function persistEndedId(id: number): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, String(id));
  } catch {
    // Silently ignore storage errors
  }
}

function clearStoredEndedId(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Silently ignore storage errors
  }
}

function DisplayVoteResult({ vote }: { vote: VoteStatistics }) {
  const maxCount = Math.max(...vote.results.map((item) => item.count), 1);
  const statusLabel =
    vote.status === "open" ? "Vote In Progress" : "Vote Result";

  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-900/80 p-8 shadow-2xl">
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase tracking-[0.25em] text-sky-400">
            {statusLabel}
          </p>
          <h2 className="mt-2 text-4xl font-bold leading-tight">
            {vote.title}
          </h2>
        </div>
        <div className="rounded-2xl border border-slate-700 bg-slate-950 px-5 py-3 text-right">
          <p className="text-3xl font-bold">{vote.total_votes}</p>
          <p className="text-xs uppercase tracking-widest text-slate-500">
            Total Votes
          </p>
        </div>
      </div>

      <div className="space-y-5">
        {vote.results.map((option) => {
          const pct =
            vote.total_votes > 0
              ? Math.round((option.count / vote.total_votes) * 100)
              : 0;
          const barWidth = maxCount > 0 ? (option.count / maxCount) * 100 : 0;
          return (
            <div key={option.option}>
              <div className="mb-2 flex items-center justify-between gap-4">
                <p className="min-w-0 truncate text-2xl font-semibold">
                  {option.option}
                </p>
                <p className="shrink-0 text-xl text-slate-300">
                  {option.count} votes / {pct}%
                </p>
              </div>
              <div className="h-4 overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full rounded-full bg-sky-400 transition-all duration-700"
                  style={{ width: `${barWidth}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
