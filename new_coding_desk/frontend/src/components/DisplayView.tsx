import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  List,
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
  fetchAgendas,
} from "../api/resources";
import { useWebSocket } from "../hooks/useWebSocket";
import type { WSMessage } from "../hooks/useWebSocket";
import type { Meeting, Agenda, VoteStatistics } from "../api/types";
import {
  ActionButton,
  DualLabel,
  StatusBadge,
  useClock,
  formatTime,
} from "./shared";
import { deriveAgendaState } from "../utils/agendaState";

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
  agendas: Agenda[];
  activeVote: VoteStatistics | null;
  voteResults: VoteStatistics[];
  currentMeetingId: number | null;
  endedMeetingId: number | null;
}

const EMPTY_STATE: DisplayState = {
  loading: true,
  error: null,
  meeting: null,
  agendas: [],
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
        const [rawActiveVote, voteResults, agendas] = await Promise.all([
          fetchActiveVote(),
          fetchVoteResultsForMeeting(meeting.id),
          fetchAgendas(meeting.id),
        ]);
        const activeVote = rawActiveVote
          ? await fetchVoteStatistics(rawActiveVote.id)
          : null;

        lastActiveMeetingIdRef.current = meeting.id;
        setState({
          loading: false,
          error: null,
          meeting,
          agendas,
          activeVote,
          voteResults,
          currentMeetingId: meeting.id,
          endedMeetingId: null,
        });
        return;
      }

      // No active meeting — check if we have an ended meeting to show
      if (endedMeetingId !== null) {
        const [voteResults, agendas] = await Promise.all([
          fetchVoteResultsForMeeting(endedMeetingId),
          fetchAgendas(endedMeetingId),
        ]);
        setState({
          loading: false,
          error: null,
          meeting: null,
          agendas,
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
        agendas: [],
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
        event === "meeting_ended" ||
        event === "agenda_updated"
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
    <div className="min-h-screen bg-techBg text-techText lg:h-screen lg:overflow-hidden lg:flex lg:flex-col">
      {/* ── Header ─────────────────────────────────────────────── */}
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-4 border-b border-techBorder px-5 py-4 lg:px-8 xl:px-10">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-techCyan/30 bg-techCyan/10 shadow-cyan-glow">
            <Monitor size={21} className="text-techCyan" />
          </div>
          <div className="min-w-0">
            <DualLabel
              cn="会议大屏"
              en="Command Display"
              className="mb-1"
              cnClassName="text-[0.65rem] font-semibold uppercase tracking-[0.22em] text-techCyan"
              enClassName="text-[0.65rem] opacity-70"
            />
            <h1 className="truncate text-2xl font-bold text-techText xl:text-3xl">
              {isEndedMeeting ? (
                <>
                  会议已结束 <span className="ml-1 text-base font-mono tracking-wider text-techMuted xl:text-lg">
                    / <span>Meeting Ended</span>
                  </span>
                </>
              ) : state.meeting?.title ? (
                state.meeting.title
              ) : (
                <>
                  等待会议开始 <span className="ml-1 text-base font-mono tracking-wider text-techMuted xl:text-lg">
                    / <span>Waiting for Meeting</span>
                  </span>
                </>
              )}
            </h1>
          </div>
        </div>
        <div className="flex items-center gap-3 lg:gap-4">
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
            <Clock size={16} />
            <span className="text-sm font-mono tabular-nums lg:text-base">
              {formatTime(now)}
            </span>
          </div>
          <ActionButton
            variant="secondary"
            size="md"
            icon={<RefreshCw size={15} />}
            onClick={load}
          >
            <span>刷新</span>
            <span>Refresh</span>
          </ActionButton>
        </div>
      </header>

      {/* ── Main content ──────────────────────────────────────── */}
      <main className="px-4 py-4 lg:min-h-0 lg:flex-1 lg:overflow-hidden lg:px-6 lg:py-5 xl:px-10 xl:py-6">
        <div className="lg:h-full">
          {/* ── Loading state ──────────────────────────────────── */}
          {state.loading && (
            <div className="flex min-h-[50vh] flex-col items-center justify-center rounded-xl border border-techBorder bg-techCard p-10 shadow-card-glow lg:h-full lg:min-h-0">
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
            <div className="flex min-h-[50vh] flex-col justify-center rounded-xl border border-techRose/30 bg-techRose/10 p-8 shadow-card-glow lg:h-full lg:min-h-0">
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
                操作失败 / Operation Failed: {state.error}
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
            <div className="flex min-h-[50vh] flex-col gap-3 lg:h-full lg:min-h-0">
              {/* ── Ended meeting banner ──────────────────────────── */}
              {isEndedMeeting && (
                <div className="flex shrink-0 items-center justify-center gap-2 rounded-lg border border-techAmber/30 bg-techAmber/10 px-4 py-2.5 text-center shadow-card-glow">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-techAmber opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-techAmber" />
                  </span>
                  <p className="text-sm font-semibold text-techAmber">
                    会议已结束，结果保留 / Meeting Ended — Results Preserved
                  </p>
                </div>
              )}

              <div
                data-testid="display-dashboard-grid"
                className="grid min-h-0 flex-1 gap-4 lg:grid-cols-12"
              >
                <div
                  data-testid="display-agenda-panel"
                  className="min-h-0 lg:col-span-4"
                >
                  <DisplayAgendaProgress agendas={state.agendas} />
                </div>
                <div
                  data-testid="display-vote-panel"
                  className="min-h-0 lg:col-span-8"
                >
                  {displayVote ? (
                    <DisplayVoteResult vote={displayVote} />
                  ) : (
                    <DisplayEmptyVote />
                  )}
                </div>
              </div>
            </div>
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

function DisplayEmptyVote() {
  return (
    <section className="flex min-h-[360px] flex-col items-center justify-center rounded-xl border border-techBorder bg-techCard p-8 text-center shadow-card-glow lg:h-full lg:min-h-0">
      <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-full border border-techBorder bg-techCardSoft text-techMuted">
        <VoteIcon size={32} />
      </div>
      <DualLabel
        cn="暂无投票"
        en="NO VOTE"
        className="justify-center"
        cnClassName="text-2xl font-bold text-techText"
        enClassName="text-sm"
      />
      <p className="mt-3 max-w-md text-sm text-techMuted">
        投票开始后，实时统计结果将在此显示。 / Live results will appear here when a vote starts.
      </p>
    </section>
  );
}

function DisplayVoteResult({ vote }: { vote: VoteStatistics }) {
  const maxCount = Math.max(...vote.results.map((item) => item.count), 1);
  const isOpen = vote.status === "open";
  const topOption = vote.results.reduce(
    (best, curr) => (curr.count > best.count ? curr : best),
    vote.results[0],
  );

  return (
    <section className="flex min-h-[360px] flex-col rounded-xl border border-techBorder bg-techCard p-5 shadow-card-glow lg:h-full lg:min-h-0 lg:p-7 xl:p-8">
      <div className="mb-5 flex shrink-0 flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-2">
            <StatusBadge
              status={isOpen ? "speaking" : "success"}
              labelCn={isOpen ? "投票进行中" : "投票结果"}
              labelEn={isOpen ? "Vote In Progress" : "Vote Result"}
              pulse={isOpen}
            />
          </div>
          <h2 className="break-words text-2xl font-bold leading-tight text-techText xl:text-3xl">
            {vote.title}
          </h2>
        </div>
        <div className="min-w-[116px] rounded-xl border border-techBorder bg-techCardSoft px-5 py-3 text-center">
          <p className="text-3xl font-bold text-techCyan xl:text-4xl">
            {vote.total_votes}
          </p>
          <p className="mt-1 text-[0.65rem] font-mono tracking-wider text-techMuted">
            总票数 / TOTAL VOTES
          </p>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1 lg:space-y-5">
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
              <div className="mb-2 flex items-start justify-between gap-4">
                <span className="flex min-w-0 items-start gap-2.5">
                  {isWinner && (
                    <span className="mt-0.5 shrink-0 text-techCyan">
                      <CheckCircle size={20} />
                    </span>
                  )}
                  <span
                    className={`break-words text-lg font-semibold leading-snug xl:text-xl ${
                      isWinner ? "text-techCyan" : "text-techText"
                    }`}
                  >
                    {option.option}
                  </span>
                  {isWinner && (
                    <span className="mt-1 shrink-0 text-[0.6rem] font-mono tracking-wider text-techCyan">
                      领先 / LEADING
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-base tabular-nums text-techMuted xl:text-lg">
                  {option.count} 票 / {option.count} votes · {pct}%
                </span>
              </div>
              <div className="h-3 overflow-hidden rounded-full bg-techCardSoft xl:h-4">
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

// ── Agenda Progress Display (read-only) ────────────────────────────────────────

function agendaStatusCopy(status: string | null | undefined) {
  switch (status) {
    case "active":
      return { cn: "进行中", en: "Active", color: "text-techCyan" };
    case "completed":
      return { cn: "已完成", en: "Completed", color: "text-techGreen" };
    case "skipped":
      return { cn: "已跳过", en: "Skipped", color: "text-techAmber" };
    default:
      return { cn: "待处理", en: "Pending", color: "text-techMuted" };
  }
}

function DisplayAgendaProgress({ agendas }: { agendas: Agenda[] }) {
  const { current, progress, isFlowDone } = deriveAgendaState(agendas);
  const sortedAgendas = [...agendas].sort(
    (a, b) => (a.sort_order ?? a.id) - (b.sort_order ?? b.id),
  );
  const progressValue =
    progress.current_index ?? (isFlowDone ? progress.total : progress.completed + progress.skipped);

  const currentCopy = current
    ? { cn: "当前议题", en: "CURRENT TOPIC" }
    : isFlowDone
      ? { cn: "所有议题已处理", en: "ALL TOPICS PROCESSED" }
      : { cn: "暂无当前议题", en: "NO ACTIVE TOPIC" };

  return (
    <section className="flex min-h-[360px] flex-col rounded-xl border border-techBorder bg-techCard p-5 shadow-card-glow lg:h-full lg:min-h-0 lg:p-6 xl:p-7">
      <div className="mb-4 shrink-0">
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-techCyan">
            <List size={18} />
            <DualLabel
              cn="议程进度"
              en="AGENDA PROGRESS"
              cnClassName="text-xs font-semibold tracking-[0.16em]"
              enClassName="text-[0.6rem]"
            />
          </div>
          <span className="shrink-0 text-lg font-bold tabular-nums text-techText">
            {progressValue} / {progress.total}
          </span>
        </div>
        <div className="rounded-lg border border-techBorder bg-techCardSoft px-3 py-3">
          <DualLabel
            cn={currentCopy.cn}
            en={currentCopy.en}
            cnClassName={current ? "text-xs font-semibold text-techCyan" : "text-xs font-semibold text-techMuted"}
            enClassName="text-[0.6rem]"
          />
          {current && (
            <p className="mt-1 break-words text-lg font-bold leading-snug text-techText xl:text-xl">
              {current.title}
            </p>
          )}
        </div>
      </div>

      {sortedAgendas.length > 0 ? (
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <ol className="relative space-y-3 border-l border-techBorder pl-4">
            {sortedAgendas.map((item) => {
              const status = agendaStatusCopy(item.status);
              const isActive = item.status === "active";
              const isCompleted = item.status === "completed";
              const isSkipped = item.status === "skipped";
              const markerClass = isActive
                ? "border-techCyan bg-techCyan shadow-cyan-glow"
                : isCompleted
                  ? "border-techGreen bg-techGreen"
                  : isSkipped
                    ? "border-techAmber bg-techAmber"
                    : "border-techBorder bg-techCardSoft";

              return (
                <li key={item.id} className="relative pl-4">
                  <span
                    className={`absolute -left-[1.1rem] top-1 flex h-7 w-7 items-center justify-center rounded-full border text-[0.65rem] font-bold ${markerClass} ${
                      isActive ? "animate-pulse" : ""
                    }`}
                  >
                    <span className={isActive || isCompleted || isSkipped ? "text-techBg" : "text-techMuted"}>
                      {item.sort_order ?? item.id}
                    </span>
                  </span>
                  <p className="break-words text-sm font-semibold leading-snug text-techText">
                    {item.title}
                  </p>
                  <p className={`mt-0.5 text-[0.6rem] font-mono tracking-wider ${status.color}`}>
                    {status.cn} / {status.en}
                  </p>
                </li>
              );
            })}
          </ol>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center text-center">
          <List size={28} className="mb-3 text-techMuted" />
          <DualLabel
            cn="暂无议程"
            en="NO AGENDA"
            className="justify-center"
            cnClassName="text-base font-semibold text-techText"
            enClassName="text-xs"
          />
          <p className="mt-2 text-xs text-techMuted">
            议程发布后将在此显示。 / The agenda will appear here when published.
          </p>
        </div>
      )}
    </section>
  );
}
