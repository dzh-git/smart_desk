import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  Loader2,
  Monitor,
  RefreshCw,
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
import { SpatialStage } from "../spatial/SpatialStage";
import type { SpatialState } from "../spatial/sceneState";
import {
  ActionButton,
  DualLabel,
  StatusBadge,
  isDemoControlsEnabled,
} from "./shared";
import { deriveAgendaState } from "../utils/agendaState";
import "./spectator.css";

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
  featuredVoteId: number | null;
  endedMeetingId: number | null;
}

const EMPTY_STATE: DisplayState = {
  loading: true,
  error: null,
  meeting: null,
  agendas: [],
  activeVote: null,
  voteResults: [],
  featuredVoteId: null,
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
      const nextAgendas = [...agendas];
      setState((previous) => {
        const sameTopic = meeting?.id === previous.meeting?.id
          && deriveAgendaState(nextAgendas).current?.id === deriveAgendaState(previous.agendas).current?.id;
        return {
          loading: false,
          error: null,
          meeting,
          agendas: nextAgendas,
          activeVote,
          voteResults: [...voteResults],
          // Keep a completed vote on the stage until the agenda advances.
          featuredVoteId: activeVote?.vote_id ?? (sameTopic ? previous.featuredVoteId : null),
          endedMeetingId,
        };
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
    state.voteResults.find((vote) => vote.status === "closed" && vote.vote_id === state.featuredVoteId) ??
    state.voteResults.find((vote) => vote.status === "closed") ??
    null;
  const agendaState = useMemo(() => deriveAgendaState(state.agendas), [state.agendas]);
  const { current, progress } = agendaState;
  const hasMeeting = state.meeting != null || isEndedMeeting;
  const showVoteFirst = displayVote && (
    displayVote.status === "open" || displayVote.vote_id === state.featuredVoteId || isEndedMeeting ||
    (!current && (agendaState.isFlowDone || progress.total === 0))
  );
  const focus = state.loading ? "loading"
    : state.error && !hasMeeting ? "error"
    : showVoteFirst ? "vote"
    : hasMeeting ? "agenda"
    : "waiting";
  const scene: SpatialState = {
    mode: "display",
    phase: state.loading ? "busy"
      : state.error ? "fault"
      : isEndedMeeting ? "complete"
      : state.activeVote?.status === "open" ? "vote"
      : state.meeting && connection !== "connected" ? "busy"
      : state.meeting ? "live"
      : "idle",
    level: progress.total ? (progress.completed + progress.skipped) / progress.total : 0,
    signal: activeMeetingId == null && !isEndedMeeting ? null : [
      activeMeetingId ?? state.endedMeetingId,
      current?.id,
      displayVote?.vote_id,
      displayVote?.status,
      displayVote?.total_votes,
    ].join(":"),
  };

  return (
    <div data-spatial-mode="display" data-spatial-phase={scene.phase} className="spectator spectator-display">
      <header className="spectator-header">
        <div className="spectator-heading">
          <Monitor size={20} aria-hidden="true" />
          <div className="min-w-0">
            <DualLabel cn="会议大屏" en="Command Display" cnClassName="text-sm" />
            {state.meeting?.title && <h1 className="spectator-meeting-title">{state.meeting.title}</h1>}
            {isEndedMeeting && (
              <h1 className="spectator-meeting-title">
                会议已结束 <span className="spectator-secondary">/ <span>Meeting Ended</span></span>
              </h1>
            )}
          </div>
        </div>
        <div className="spectator-actions">
          {isDemoControlsEnabled() && (
            <StatusBadge status="warning" labelCn="演示模式" labelEn="Demo Mode" />
          )}
          {activeMeetingId != null && connection !== "connected" && (
            <StatusBadge status="warning" labelCn="实时连接恢复中" labelEn="Syncing" />
          )}
          <ActionButton
            className="spectator-control"
            variant="ghost"
            size="sm"
            icon={<RefreshCw size={15} />}
            loading={refreshing}
            onClick={() => void load()}
          >
            <span>刷新</span>
            <span>Refresh</span>
          </ActionButton>
        </div>
      </header>

      <main
        data-testid={focus === "loading" || focus === "error" ? undefined : "display-dashboard-grid"}
        className="spectator-display__main"
      >
        <SpatialStage state={scene} className="spectator-stage spectator-display__stage" showTitle={false} />

        <div data-testid="display-focus" data-focus={focus} className="spectator-display__focus">
          {isEndedMeeting && (
            <p className="spectator-kicker text-techAmber">会议已结束，结果保留 / Meeting Ended — Results Preserved</p>
          )}
          {focus === "loading" && (
            <div role="status" className="spectator-state">
              <Loader2 size={26} className="animate-spin text-techCyan" aria-hidden="true" />
              <h1 className="spectator-focus-title">正在加载大屏数据</h1>
              <p className="spectator-secondary">Loading Display</p>
            </div>
          )}
          {focus === "waiting" && (
            <div className="spectator-state">
              <h1 className="spectator-focus-title">等待会议开始</h1>
              <p className="spectator-secondary">Waiting for Meeting</p>
            </div>
          )}
          {focus === "error" && (
            <div role="alert" className="spectator-state">
              <AlertTriangle size={26} className="text-techRose" aria-hidden="true" />
              <h1 className="spectator-focus-title">大屏数据加载失败</h1>
              <p className="spectator-secondary">Display Load Failed</p>
              <ActionButton variant="secondary" icon={<RefreshCw size={16} />} onClick={() => void load()}>
                刷新重试 / Retry
              </ActionButton>
            </div>
          )}
          {focus === "agenda" && (
            <section data-testid="display-agenda-panel">
              <DisplayAgendaFocus agendaState={agendaState} showProgress={state.agendas.length > 0} />
              {state.agendas.length > 0 && <DisplayAgendaList agendas={state.agendas} />}
            </section>
          )}
          {focus === "vote" && displayVote && (
            <>
              <DisplayVoteResult vote={displayVote} />
              {state.agendas.length > 0 && <DisplayAgendaList agendas={state.agendas} secondary />}
            </>
          )}
          {focus === "agenda" && displayVote && (
            <details className="spectator-disclosure">
              <summary>最近投票 / Last Vote <ChevronDown size={16} aria-hidden="true" /></summary>
              <DisplayVoteResult vote={displayVote} />
            </details>
          )}
          {state.error && (
            <div className="mt-4">
              {hasMeeting && <p role="alert" className="text-sm text-techAmber">更新失败 / Sync failed</p>}
              <details className="spectator-disclosure">
                <summary>同步详情 / Sync Details <ChevronDown size={16} aria-hidden="true" /></summary>
                <p className="spectator-detail-text">{state.error}</p>
              </details>
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

function DisplayVoteResult({ vote }: { vote: VoteStatistics }) {
  const maxCount = Math.max(...vote.results.map((item) => item.count), 1);
  const isOpen = vote.status === "open";
  const hasClearWinner = vote.results.filter((option) => option.count === maxCount).length === 1;

  return (
    <section data-testid="display-vote-panel" className="spectator-vote">
      <p className="spectator-kicker">
        {isOpen ? "投票进行中" : "投票结果"} <span>{isOpen ? "Vote In Progress" : "Vote Result"}</span>
      </p>
      <h2 className="spectator-focus-title">{vote.title}</h2>
      <p className="spectator-secondary spectator-vote__total">
        <strong className="text-techCyan">{vote.total_votes}</strong> 总票数 / Total Votes
      </p>
      <ul className="spectator-vote__results">
        {vote.results.map((option) => {
          const pct =
            vote.total_votes > 0
              ? Math.round((option.count / vote.total_votes) * 100)
              : 0;
          const isWinner =
            hasClearWinner && option.count === maxCount && !isOpen;

          return (
            <li key={option.option}>
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="flex min-w-0 flex-wrap items-center gap-2">
                  {isWinner && (
                    <span className="mt-0.5 shrink-0 text-techCyan">
                      <CheckCircle size={20} aria-hidden="true" />
                    </span>
                  )}
                  <span
                    className={`spectator-vote__option ${isWinner ? "text-techCyan" : "text-techText"}`}
                  >
                    {option.option}
                  </span>
                  {isWinner && (
                    <span className="mt-1 shrink-0 text-[0.6rem] font-mono tracking-wider text-techCyan">
                      领先 / LEADING
                    </span>
                  )}
                </span>
                <span className="spectator-secondary tabular-nums">
                  {option.count} 票 / {option.count} votes · {pct}%
                </span>
              </div>
              <div className="spectator-vote__track" aria-hidden="true">
                <div className="spectator-vote__fill" style={{ width: `${pct}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
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

function DisplayAgendaFocus({ agendaState, showProgress }: {
  agendaState: ReturnType<typeof deriveAgendaState>;
  showProgress: boolean;
}) {
  const { current, progress, isFlowDone } = agendaState;
  const progressValue =
    progress.current_index ?? (isFlowDone ? progress.total : progress.completed + progress.skipped);
  const inactiveTitle = !showProgress ? "暂无议程" : isFlowDone ? "所有议题已处理" : "暂无当前议题";
  const inactiveSubtitle = !showProgress ? "NO AGENDA" : isFlowDone ? "ALL TOPICS PROCESSED" : "NO ACTIVE TOPIC";

  return (
    <div className="spectator-state">
      {current && <p className="spectator-kicker"><span>当前议题</span> <span>CURRENT TOPIC</span></p>}
      <h2 className="spectator-focus-title">{current?.title ?? inactiveTitle}</h2>
      {!current && <p className="spectator-secondary">{inactiveSubtitle}</p>}
      {showProgress && (
        <div className="spectator-progress">
          <span>议程进度 / Agenda Progress</span>
          <strong className="tabular-nums text-techText">{progressValue} / {progress.total}</strong>
          <progress aria-label="议程进度 / Agenda Progress" max={progress.total} value={progressValue} />
        </div>
      )}
    </div>
  );
}

function DisplayAgendaList({ agendas, secondary = false }: { agendas: Agenda[]; secondary?: boolean }) {
  const ordered = [...agendas].sort((a, b) => (a.sort_order ?? a.id) - (b.sort_order ?? b.id));
  return (
    <details className="spectator-disclosure" data-testid={secondary ? "display-agenda-panel" : undefined}>
      <summary>完整议程 / Full Agenda <ChevronDown size={16} aria-hidden="true" /></summary>
      <ol className="spectator-agenda-list">
        {ordered.map((item) => {
          const status = agendaStatusCopy(item.status);
          return (
            <li key={item.id} aria-current={item.status === "active" ? "step" : undefined}>
              <span className="spectator-secondary tabular-nums">{item.sort_order ?? item.id}</span>
              <span className="break-words">{item.title}</span>
              <span className={`text-xs ${status.color}`}>{status.cn} / {status.en}</span>
            </li>
          );
        })}
      </ol>
    </details>
  );
}
