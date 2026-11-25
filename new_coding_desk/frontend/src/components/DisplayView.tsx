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
  isDemoControlsEnabled,
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
  endedMeetingId: number | null;
}

const EMPTY_STATE: DisplayState = {
  loading: true,
  error: null,
  meeting: null,
  agendas: [],
  activeVote: null,
  voteResults: [],
  endedMeetingId: null,
};

export function DisplayView() {
  const [state, setState] = useState<DisplayState>(() => ({
    ...EMPTY_STATE,
    endedMeetingId: tryGetStoredEndedId(),
  }));
  const endedMeetingIdRef = useRef(state.endedMeetingId);
  const lastActiveMeetingIdRef = useRef<number | null>(null);
  const requestVersion = useRef(0);
  const loadingSnapshot = useRef(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (checkForNextMeeting = false, polling = false) => {
    if (polling && loadingSnapshot.current) return;
    const version = ++requestVersion.current;
    loadingSnapshot.current = true;
    if (!checkForNextMeeting) setRefreshing(true);
    try {
      const meeting = await fetchActiveMeeting();
      if (version !== requestVersion.current) return;

      const endedMeetingId = meeting
        ? null
        : endedMeetingIdRef.current ?? lastActiveMeetingIdRef.current;
      if (checkForNextMeeting && !meeting && endedMeetingId === endedMeetingIdRef.current) {
        setState((previous) => previous.error ? { ...previous, error: null } : previous);
        return;
      }

      const meetingId = meeting?.id ?? endedMeetingId;
      const [rawActiveVote, voteResults, agendas] = meetingId == null
        ? [null, [], []] as const
        : await Promise.all([
            meeting ? fetchActiveVote() : null,
            fetchVoteResultsForMeeting(meetingId),
            fetchAgendas(meetingId),
          ]);
      const activeVote = rawActiveVote && rawActiveVote.meeting_id === meetingId
        ? voteResults.find((vote) => vote.vote_id === rawActiveVote.id)
          ?? await fetchVoteStatistics(rawActiveVote.id)
        : null;
      if (version !== requestVersion.current) return;

      lastActiveMeetingIdRef.current = meeting?.id ?? null;
      endedMeetingIdRef.current = endedMeetingId;
      if (endedMeetingId != null) persistEndedId(endedMeetingId);
      else clearStoredEndedId();
      setState({
        loading: false,
        error: null,
        meeting,
        agendas: [...agendas],
        activeVote,
        voteResults: [...voteResults],
        endedMeetingId,
      });
    } catch (err) {
      if (version !== requestVersion.current) return;
      setState((previous) => ({
        ...previous,
        loading: false,
        error: err instanceof Error ? err.message : "Failed to load display",
      }));
    } finally {
      if (version === requestVersion.current) {
        loadingSnapshot.current = false;
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleEvent = useCallback(
    (event: string, message: WSMessage) => {
      if (event === "meeting_ended") {
        const meetingId = message.meeting_id || lastActiveMeetingIdRef.current;
        if (meetingId != null) {
          endedMeetingIdRef.current = meetingId;
          persistEndedId(meetingId);
        }
      }
      if ([
        "meeting_ended",
        "vote_started",
        "vote_updated",
        "vote_closed",
        "agenda_updated",
        "reconnected",
      ].includes(event)) void load();
    },
    [load],
  );

  const activeMeetingId = state.meeting?.id ?? null;
  const isEndedMeeting = activeMeetingId == null && state.endedMeetingId != null;
  const connection = useWebSocket(activeMeetingId, handleEvent, 0);

  useEffect(() => {
    if (state.loading || (activeMeetingId != null && connection === "connected" && !state.error)) {
      return;
    }
    const checkForNextMeeting = activeMeetingId == null && !state.error;
    const timer = window.setInterval(() => void load(checkForNextMeeting, true), DISPLAY_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [activeMeetingId, connection, load, state.error, state.loading]);

  const displayVote =
    state.activeVote ??
    state.voteResults.find((vote) => vote.status === "closed") ??
    null;

  // ── Live clock for header ────────────────────────────────────────────────
  const now = useClock();

  return (
    <div className="desk-page min-h-screen text-techText lg:h-dvh lg:flex lg:flex-col">
      {/* ── Header ─────────────────────────────────────────────── */}
      <header className="desk-hero flex shrink-0 flex-wrap items-center justify-between gap-5 border-b border-techBorder px-5 py-6 lg:px-9 xl:px-12 xl:py-9">
        <div className="flex min-w-0 items-center gap-4 sm:gap-6">
          <div className="desk-brand-mark flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-techCyan/30 bg-techCyan/10 sm:h-16 sm:w-16">
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
            <h1 className="break-words text-3xl font-semibold leading-tight text-techText sm:text-4xl xl:text-6xl">
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
        <div className="flex flex-wrap items-center gap-3 lg:gap-4">
          {isDemoControlsEnabled() && (
            <StatusBadge status="warning" labelCn="演示模式" labelEn="Demo Mode" />
          )}
          {activeMeetingId != null && connection !== "connected" && (
            <StatusBadge status="warning" labelCn="实时连接恢复中" labelEn="Syncing" />
          )}
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
            loading={refreshing}
            onClick={() => void load()}
          >
            <span>刷新</span>
            <span>Refresh</span>
          </ActionButton>
        </div>
      </header>

      {/* ── Main content ──────────────────────────────────────── */}
      <main className="px-4 py-4 lg:min-h-0 lg:flex-1 lg:px-9 lg:py-6 xl:px-12 xl:py-8">
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
          {!state.loading && state.error && !state.meeting && !isEndedMeeting && (
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
                onClick={() => void load()}
              >
                <span>刷新重试</span>
                <span>Retry</span>
              </ActionButton>
            </div>
          )}

          {/* ── Normal content (not loading, no error) ─────────── */}
          {!state.loading && (!state.error || state.meeting || isEndedMeeting) && (
            <div className="flex min-h-[50vh] flex-col gap-3 lg:h-full lg:min-h-0">
              {state.error && (
                <p role="alert" className="rounded-xl border border-techRose/30 bg-techRose/10 px-4 py-3 text-sm text-techRose">
                  更新失败 / Sync failed · {state.error}
                </p>
              )}
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
                className="grid min-h-0 flex-1 gap-4 lg:grid-cols-12 xl:gap-6"
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
    <section className="desk-panel flex min-h-[360px] flex-col items-center justify-center rounded-xl border border-techBorder bg-techCard p-8 text-center shadow-card-glow lg:h-full lg:min-h-0">
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
  const hasClearWinner = vote.results.filter((option) => option.count === maxCount).length === 1;

  return (
    <section className="desk-panel flex min-h-[360px] flex-col rounded-xl border border-techBorder bg-techCard p-5 shadow-card-glow lg:h-full lg:min-h-0 lg:p-7 xl:p-8">
      <div className="mb-7 flex shrink-0 flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-2">
            <StatusBadge
              status={isOpen ? "speaking" : "success"}
              labelCn={isOpen ? "投票进行中" : "投票结果"}
              labelEn={isOpen ? "Vote In Progress" : "Vote Result"}
              pulse={isOpen}
            />
          </div>
          <h2 className="break-words text-2xl font-semibold leading-tight text-techText xl:text-4xl">
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
          const isWinner =
            hasClearWinner && option.count === maxCount && !isOpen;

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
              <div className="h-3 overflow-hidden rounded-full border border-techBorder bg-techSurface xl:h-5">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${
                    isWinner ? "bg-techCyan" : "bg-techBlue/60"
                  }`}
                  style={{ width: `${pct}%` }}
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
    <section className="desk-panel flex min-h-[360px] flex-col rounded-xl border border-techBorder bg-techCard p-5 shadow-card-glow lg:h-full lg:min-h-0 lg:p-6 xl:p-7">
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
          <ol className="relative ml-1 space-y-1">
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
                <li key={item.id} className="relative flex flex-col gap-1 rounded-xl border border-transparent py-2 pl-11 pr-3 hover:border-techBorder">
                  <span
                    className={`absolute left-1 top-2 flex h-7 w-7 items-center justify-center rounded-full border text-[0.65rem] font-bold ${markerClass} ${
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
