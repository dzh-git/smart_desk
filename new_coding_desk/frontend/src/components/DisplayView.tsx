import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Loader2,
  Monitor,
  RefreshCw,
  Vote as VoteIcon,
} from "lucide-react";
import {
  fetchActiveMeeting,
  fetchActiveVote,
  fetchVoteResultsForMeeting,
  fetchVoteStatistics,
} from "../api/resources";
import { useWebSocket } from "../hooks/useWebSocket";
import type { WSMessage } from "../hooks/useWebSocket";
import type { Meeting, VoteStatistics } from "../api/types";
import {
  ActionButton,
  DualLabel,
  StatusBadge,
  useClock,
  formatTime,
} from "./shared";

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

  // ── Live clock for header ────────────────────────────────────────────────
  const now = useClock();

  return (
    <div className="min-h-screen bg-techBg text-techText">
      {/* ── Header ─────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-center justify-between gap-6 border-b border-techBorder px-10 py-8">
        <div className="flex min-w-0 items-center gap-5">
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border border-techCyan/30 bg-techCyan/10 shadow-cyan-glow">
            <Monitor size={30} className="text-techCyan" />
          </div>
          <div className="min-w-0">
            <DualLabel
              cn="会议大屏"
              en="Command Display"
              className="mb-1"
              cnClassName="text-xs font-semibold uppercase tracking-[0.3em] text-techCyan"
              enClassName="text-[0.65rem] opacity-70"
            />
            <h1 className="truncate text-4xl font-bold text-techText">
              {isEndedMeeting ? (
                <>
                  会议已结束{" "}
                  <span className="text-2xl font-mono tracking-wider text-techMuted">
                    Meeting Ended
                  </span>
                </>
              ) : state.meeting?.title ? (
                state.meeting.title
              ) : (
                <>
                  等待会议开始{" "}
                  <span className="text-2xl font-mono tracking-wider text-techMuted">
                    Waiting for Meeting
                  </span>
                </>
              )}
            </h1>
          </div>
        </div>
        <div className="flex items-center gap-6">
          {!state.loading && !state.error && (
            <>
              {state.meeting && (
                <StatusBadge
                  status="speaking"
                  labelCn="进行中"
                  labelEn="In Progress"
                  pulse
                />
              )}
              {isEndedMeeting && (
                <StatusBadge
                  status="warning"
                  labelCn="已结束"
                  labelEn="Ended"
                />
              )}
            </>
          )}
          <div className="flex items-center gap-2 text-techMuted">
            <Clock size={20} />
            <span className="text-lg font-mono tabular-nums">
              {formatTime(now)}
            </span>
          </div>
          <ActionButton
            variant="secondary"
            size="lg"
            icon={<RefreshCw size={18} />}
            onClick={load}
          >
            <span>刷新</span>
            <span>Refresh</span>
          </ActionButton>
        </div>
      </header>

      {/* ── Main content ──────────────────────────────────────── */}
      <main className="mx-auto max-w-7xl px-10 py-10">
        <div className="space-y-8">
          {/* ── Loading state ──────────────────────────────────── */}
          {state.loading && (
            <div className="flex flex-col items-center justify-center rounded-xl border border-techBorder bg-techCard p-16 shadow-card-glow">
              <Loader2 size={48} className="animate-spin text-techCyan" />
              <div className="mt-6 text-center">
                <p className="text-2xl font-semibold text-techText">
                  正在加载大屏数据
                </p>
                <p className="mt-1 text-sm font-mono tracking-wider text-techMuted">
                  Loading Display
                </p>
              </div>
            </div>
          )}

          {/* ── Error state ────────────────────────────────────── */}
          {!state.loading && state.error && (
            <div className="rounded-xl border border-techRose/30 bg-techRose/10 p-10 shadow-card-glow">
              <div className="mb-4 flex items-center gap-4">
                <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-techRose/20">
                  <AlertTriangle size={28} className="text-techRose" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-techRose">
                    大屏数据加载失败
                  </p>
                  <p className="mt-0.5 text-sm font-mono tracking-wider text-techMuted">
                    Display Load Failed
                  </p>
                </div>
              </div>
              <p className="mb-6 text-base text-techMuted/80">
                {state.error}
              </p>
              <ActionButton
                variant="danger"
                icon={<RefreshCw size={18} />}
                onClick={load}
              >
                <span>刷新重试</span>
                <span>Retry</span>
              </ActionButton>
            </div>
          )}

          {/* ── Normal content (not loading, no error) ─────────── */}
          {!state.loading && !state.error && (
            <>
              {/* ── Ended meeting banner ──────────────────────────── */}
              {isEndedMeeting && (
                <div className="rounded-xl border border-techAmber/30 bg-techAmber/10 p-8 text-center shadow-card-glow">
                  <div className="mb-2 flex items-center justify-center gap-3">
                    <span className="relative flex h-3 w-3">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-techAmber opacity-75" />
                      <span className="relative inline-flex h-3 w-3 rounded-full bg-techAmber" />
                    </span>
                    <span className="text-2xl font-bold text-techAmber">
                      会议已结束
                    </span>
                  </div>
                  <p className="text-lg text-techMuted">
                    <span>结果保留</span>
                    <span className="ml-2 text-base font-mono tracking-wider">
                      Results Preserved
                    </span>
                  </p>
                </div>
              )}

              {/* ── Vote results ─────────────────────────────────── */}
              {displayVote && <DisplayVoteResult vote={displayVote} />}

              {/* ── No vote empty state ──────────────────────────── */}
              {!displayVote && (
                <div className="flex flex-col items-center justify-center rounded-xl border border-techBorder bg-techCard p-16 text-center shadow-card-glow">
                  <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-full border border-techBorder bg-techCardSoft text-techMuted">
                    <VoteIcon size={40} />
                  </div>
                  <span className="mb-3 inline-flex items-baseline gap-3">
                    <span className="text-3xl font-bold text-techText">
                      暂无投票
                    </span>
                    <span className="text-lg font-mono tracking-wider text-techMuted">
                      No Vote
                    </span>
                  </span>
                  <p className="max-w-lg text-base text-techMuted">
                    投票结果将在会议投票开始后显示。
                  </p>
                  <p className="mt-1 text-xs font-mono text-techMuted/60">
                    Voting results will appear here once available.
                  </p>
                </div>
              )}
            </>
          )}
        </div>
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

// ── Vote result display ──────────────────────────────────────────────────────

function DisplayVoteResult({ vote }: { vote: VoteStatistics }) {
  const maxCount = Math.max(...vote.results.map((item) => item.count), 1);
  const isOpen = vote.status === "open";

  // Find the winning option for visual highlight (display only, no data change)
  const topOption = vote.results.reduce(
    (best, curr) => (curr.count > best.count ? curr : best),
    vote.results[0],
  );

  return (
    <section className="rounded-xl border border-techBorder bg-techCard p-10 shadow-card-glow">
      <div className="mb-8 flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="mb-3">
            <StatusBadge
              status={isOpen ? "speaking" : "success"}
              labelCn={isOpen ? "投票中" : "投票结果"}
              labelEn={isOpen ? "Vote In Progress" : "Vote Result"}
              pulse={isOpen}
            />
          </div>
          <h2 className="break-words text-5xl font-bold leading-tight text-techText">
            {vote.title}
          </h2>
        </div>
        <div className="min-w-[140px] rounded-xl border border-techBorder bg-techCardSoft px-8 py-5 text-center">
          <p className="text-5xl font-bold text-techCyan">
            {vote.total_votes}
          </p>
          <p className="mt-1 text-xs font-mono uppercase tracking-wider text-techMuted">
            总票数 Total Votes
          </p>
        </div>
      </div>

      <div className="space-y-6">
        {vote.results.map((option) => {
          const pct =
            vote.total_votes > 0
              ? Math.round((option.count / vote.total_votes) * 100)
              : 0;
          const barWidth = maxCount > 0 ? (option.count / maxCount) * 100 : 0;
          const isWinner =
            option.option === topOption.option && option.count > 0 && !isOpen;

          return (
            <div key={option.option}>
              <div className="mb-3 flex items-center justify-between gap-4">
                <span className="flex min-w-0 items-center gap-3">
                  {isWinner && (
                    <span className="shrink-0 text-techCyan">
                      <CheckCircle size={24} />
                    </span>
                  )}
                  <span
                    className={`truncate text-3xl font-semibold ${
                      isWinner ? "text-techCyan" : "text-techText"
                    }`}
                  >
                    {option.option}
                  </span>
                  {isWinner && (
                    <span className="shrink-0 text-xs font-mono uppercase tracking-wider text-techCyan">
                      领先 Leading
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-2xl tabular-nums text-techMuted">
                  {option.count} 票 / {pct}%
                </span>
              </div>
              <div className="h-4 overflow-hidden rounded-full bg-techCardSoft">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${
                    isWinner ? "bg-techCyan" : "bg-techBlue/60"
                  }`}
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
