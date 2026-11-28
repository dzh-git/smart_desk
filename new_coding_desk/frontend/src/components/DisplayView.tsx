import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle,
  ChevronDown,
  Loader2,
  Maximize,
  Minimize,
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
import { getVoteShares, type SpatialState } from "../spatial/sceneState";
import {
  ActionButton,
  DualLabel,
  StatusBadge,
  isDemoControlsEnabled,
} from "./shared";
import { deriveAgendaState } from "../utils/agendaState";
import "./spectator.css";
import "./display.css";

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

  const [fullscreen, setFullscreen] = useState(() => Boolean(document.fullscreenElement));
  const [fullscreenError, setFullscreenError] = useState<string | null>(null);

  useEffect(() => {
    const sync = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  async function toggleFullscreen() {
    setFullscreenError(null);
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else if (document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen();
      } else {
        setFullscreenError("浏览器未提供全屏功能");
      }
    } catch (reason) {
      setFullscreenError(reason instanceof Error ? reason.message : "当前设备无法切换全屏");
    }
  }

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
  const orderedAgendas = useMemo(() => [...state.agendas].sort(
    (first, second) => (first.sort_order ?? first.id) - (second.sort_order ?? second.id),
  ), [state.agendas]);
  const nextTopic = orderedAgendas.find((topic) => topic.status === "pending"
    && (!current || (topic.sort_order ?? topic.id) > (current.sort_order ?? current.id)));
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
    mode: focus === "vote" ? "vote" : "display",
    phase: state.loading ? "busy"
      : state.error ? "fault"
      : isEndedMeeting ? "complete"
      : state.activeVote?.status === "open" ? "vote"
      : state.meeting && connection !== "connected" ? "busy"
      : state.meeting ? "live"
      : "idle",
    level: progress.total ? (progress.completed + progress.skipped) / progress.total : 0,
    voteShares: focus === "vote" && displayVote ? getVoteShares(displayVote) : undefined,
    signal: activeMeetingId == null && !isEndedMeeting ? null : [
      activeMeetingId ?? state.endedMeetingId,
      current?.id,
      displayVote?.vote_id,
      displayVote?.status,
      displayVote?.total_votes,
    ].join(":"),
  };

  const isVotingFocus = focus === "vote" && displayVote != null;
  const hasDetails = orderedAgendas.length > 0 || (focus === "agenda" && displayVote != null) || state.error;

  return (
    <div data-spatial-mode={scene.mode} data-spatial-phase={scene.phase} className="spectator spectator-display display-page">
      <header className="display-header">
        <div className="display-header__identity">
          <div className="display-header__mark"><Monitor size={23} aria-hidden="true" /></div>
          <div className="min-w-0">
            <DualLabel cn="会议大屏" en="SmartDesk" cnClassName="text-sm" />
            {state.meeting?.title && <h1 className="display-header__title">{state.meeting.title}</h1>}
            {isEndedMeeting && (
              <h1 className="display-header__title">会议已结束 <span>Meeting Ended</span></h1>
            )}
          </div>
        </div>
        <div className="display-header__actions">
          {isDemoControlsEnabled() && <StatusBadge status="warning" labelCn="演示模式" labelEn="Demo Mode" />}
          {activeMeetingId != null && (
            <span className="display-connection" data-connected={connection === "connected" && !state.error}>
              {connection === "connected" && !state.error ? "实时同步" : "同步恢复中"}
            </span>
          )}
          <ActionButton
            className="display-command" variant="ghost" size="sm" touch icon={<RefreshCw size={16} />}
            loading={refreshing} onClick={() => void load()}
          >
            <span>刷新</span><span>Refresh</span>
          </ActionButton>
          <ActionButton
            className="display-command" variant="secondary" size="sm" touch
            icon={fullscreen ? <Minimize size={16} /> : <Maximize size={16} />}
            onClick={() => void toggleFullscreen()}
            aria-label={fullscreen ? "退出全屏 / Exit fullscreen" : "全屏 / Fullscreen"}
          >
            {fullscreen ? "退出全屏" : "全屏"}
          </ActionButton>
        </div>
      </header>

      <main
        data-testid={focus === "loading" || focus === "error" ? undefined : "display-dashboard-grid"}
        className="display-main"
      >
        {fullscreenError && <p className="display-notice" role="alert">无法切换全屏 · {fullscreenError}</p>}
        <div className="display-board" data-focus={focus}>
          <div data-testid="display-focus" data-focus={focus} className="display-focus">
            <div className="display-focus__light" aria-hidden="true" />
            {isEndedMeeting && (
              <p className="display-kicker">
                {isVotingFocus ? "结果已保留" : "会后回顾"} <span>{isVotingFocus ? "Results Preserved" : "Meeting Review"}</span>
              </p>
            )}
            {focus === "loading" && (
              <div role="status" className="display-state">
                <Loader2 size={26} className="animate-spin" aria-hidden="true" />
                <h2 className="display-title">正在加载大屏数据</h2>
                <p className="display-secondary">Loading Display</p>
              </div>
            )}
            {focus === "waiting" && (
              <div className="display-state">
                <p className="display-kicker">会议即将开始 <span>Waiting for Meeting</span></p>
                <h2 className="display-title">等待会议开始</h2>
                <p className="display-secondary">主持人开始会议后，这里会自动更新。</p>
              </div>
            )}
            {focus === "error" && (
              <div role="alert" className="display-state">
                <AlertTriangle size={26} className="text-techRose" aria-hidden="true" />
                <h2 className="display-title">大屏数据加载失败</h2>
                <ActionButton variant="secondary" icon={<RefreshCw size={16} />} loading={refreshing} onClick={() => void load()}>
                  刷新重试 / Retry
                </ActionButton>
              </div>
            )}
            {focus === "agenda" && (
              <section data-testid="display-agenda-panel">
                <DisplayAgendaFocus agendaState={agendaState} showProgress={orderedAgendas.length > 0} />
              </section>
            )}
            {isVotingFocus && <DisplayVoteResult vote={displayVote} featured />}
            {state.error && hasMeeting && <p role="alert" className="display-notice">更新失败 / Sync failed</p>}
          </div>

          <aside className="display-visual" aria-label="会议信息 / Meeting context">
            {focus !== "loading" && <SpatialStage state={scene} className="display-visual__stage" showTitle={false} />}
            {isVotingFocus && (
              <div className="display-visual__tally">
                <p>总票数 <span>Total votes</span></p>
                <strong>{String(displayVote.total_votes).padStart(2, "0")}</strong>
              </div>
            )}
            {focus === "agenda" && !isEndedMeeting && nextTopic && (
              <div className="display-visual__next">
                <ArrowRight size={20} aria-hidden="true" />
                <div>
                  <p>下一议题 <span>Up next</span></p>
                  <strong>{nextTopic.title}</strong>
                </div>
              </div>
            )}
          </aside>
        </div>

        {hasDetails && (
          <div className="display-dock">
            {orderedAgendas.length > 0 && <DisplayAgendaList agendas={orderedAgendas} secondary={isVotingFocus} />}
            {focus === "agenda" && displayVote && (
              <details className="display-disclosure">
                <summary>最近投票 / Last Vote <ChevronDown size={17} aria-hidden="true" /></summary>
                <DisplayVoteResult vote={displayVote} />
              </details>
            )}
            {state.error && (
              <details className="display-disclosure">
                <summary>同步详情 / Sync Details <ChevronDown size={17} aria-hidden="true" /></summary>
                <p className="display-secondary">{state.error}</p>
              </details>
            )}
          </div>
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

// ── Vote result display ──────────────────────────────────────────────────────

function DisplayVoteResult({ vote, featured = false }: { vote: VoteStatistics; featured?: boolean }) {
  const maxCount = Math.max(...vote.results.map((item) => item.count), 1);
  const isOpen = vote.status === "open";
  const hasClearWinner = vote.results.filter((option) => option.count === maxCount).length === 1;

  return (
    <section data-testid="display-vote-panel" className="display-vote">
      <div className="display-vote__intro">
        <p className="display-kicker">{isOpen ? "投票进行中" : "投票结果"} <span>{isOpen ? "Vote In Progress" : "Vote Result"}</span></p>
        <h2 className="display-title">{vote.title}</h2>
        {!featured && <p className="display-secondary">{vote.total_votes} 总票数 / Total Votes</p>}
      </div>
      <ul className="display-vote__results" aria-label="各选项得票 / Votes by option">
        {vote.results.map((option) => {
          const pct = vote.total_votes > 0 ? Math.round((option.count / vote.total_votes) * 100) : 0;
          const isWinner = hasClearWinner && option.count === maxCount && !isOpen;
          return (
            <li className="display-vote__option" data-leading={isWinner} key={option.option}>
              <div className="display-vote__name">
                {isWinner && <CheckCircle size={20} aria-hidden="true" />}
                <span>{option.option}</span>
                {isWinner && <small>领先 / Leading</small>}
              </div>
              <div className="display-vote__count">
                <strong>{pct}%</strong>
                <span>{option.count} 票 / {option.count} votes</span>
              </div>
              <div className="display-vote__track" aria-hidden="true">
                <div className="display-vote__fill" style={{ width: `${pct}%` }} />
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
    <div className="display-state">
      {current && <p className="display-kicker"><span>当前议题</span> <span>CURRENT TOPIC</span></p>}
      <h2 className="display-title">{current?.title ?? inactiveTitle}</h2>
      {!current && <p className="display-secondary">{inactiveSubtitle}</p>}
      {showProgress && (
        <div className="display-progress">
          <span>议程进度 / Agenda Progress</span>
          <strong className="tabular-nums text-techText">{progressValue} / {progress.total}</strong>
          <progress aria-label="议程进度 / Agenda Progress" max={progress.total} value={progressValue} />
        </div>
      )}
    </div>
  );
}

function DisplayAgendaList({ agendas, secondary = false }: { agendas: Agenda[]; secondary?: boolean }) {
  return (
    <details className="display-disclosure" data-testid={secondary ? "display-agenda-panel" : "display-agenda-details"}>
      <summary>完整议程 / Full Agenda <ChevronDown size={16} aria-hidden="true" /></summary>
      <ol className="display-agenda-list">
        {agendas.map((item) => {
          const status = agendaStatusCopy(item.status);
          return (
            <li key={item.id} aria-current={item.status === "active" ? "step" : undefined}>
              <span className="display-secondary tabular-nums">{item.sort_order ?? item.id}</span>
              <span className="break-words">{item.title}</span>
              <span className={`text-xs ${status.color}`}>{status.cn} / {status.en}</span>
            </li>
          );
        })}
      </ol>
    </details>
  );
}
