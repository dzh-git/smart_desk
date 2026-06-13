import { Vote as VoteIcon, AlertCircle, RefreshCw, CheckCircle2, Loader2 } from "lucide-react";
import { PanelCard, TechEmptyState, StatusBadge, ActionButton, DualLabel } from "./shared";
import type { VoteStatistics } from "../api/types";

interface VotePanelProps {
  vote: VoteStatistics | null;
  /** Current and historical vote statistics, newest first. */
  voteResults?: VoteStatistics[];
  /** True when the backend reports an active vote but statistics failed to load. */
  hasActiveVote?: boolean;
  /** Error message from a failed vote statistics fetch. */
  voteStatsError?: string | null;
  /** Callback to retry fetching vote statistics. */
  onRetryStats?: () => void;
  /** Callback to close the current open vote (admin). */
  onCloseVote?: (voteId: number) => void;
  /** True while close operation is in flight. */
  closingVote?: boolean;
}

export function VotePanel({
  vote,
  voteResults = [],
  hasActiveVote = false,
  voteStatsError = null,
  onRetryStats,
  onCloseVote,
  closingVote = false,
}: VotePanelProps) {
  if (hasActiveVote && !vote && voteStatsError) {
    return (
      <PanelCard titleCn="投票" titleEn="Vote" variant="warning">
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <div className="w-12 h-12 rounded-full bg-techCardSoft border border-techAmber/30 flex items-center justify-center text-techAmber mb-3">
            <AlertCircle size={20} />
          </div>
          <p className="text-sm font-semibold text-techText mb-1">
            投票统计数据不可用 / Vote Statistics Unavailable
          </p>
          <p className="text-xs text-techMuted mb-4 max-w-xs">
            {voteStatsError}
          </p>
          {onRetryStats && (
            <ActionButton
              variant="secondary"
              size="sm"
              icon={<RefreshCw size={12} />}
              onClick={onRetryStats}
            >
              Retry
            </ActionButton>
          )}
        </div>
      </PanelCard>
    );
  }

  const latestClosedVote =
    voteResults.find((item) => item.status === "closed") ?? null;
  const displayVote = vote ?? latestClosedVote;
  const isRecentResult = !vote && latestClosedVote != null;

  if (!displayVote) {
    return (
      <PanelCard titleCn="投票" titleEn="Vote">
        <TechEmptyState
          icon={<VoteIcon size={20} />}
          titleCn="暂无投票"
          titleEn="No Vote"
          descriptionCn="主持人发起投票后将在此显示"
          descriptionEn="Votes and results appear when initiated"
        />
      </PanelCard>
    );
  }

  const maxCount = Math.max(...displayVote.results.map((o) => o.count), 1);

  return (
    <PanelCard
      titleCn={isRecentResult ? "投票结果" : "当前投票"}
      titleEn={isRecentResult ? "Vote Results" : "Active Vote"}
      variant={displayVote.status === "open" ? "active" : "default"}
      headerRight={
        displayVote.status === "open" ? (
          <StatusBadge
            status="online"
            labelCn="进行中"
            labelEn="Open"
            pulse
          />
        ) : (
          <StatusBadge
            status="neutral"
            labelCn="已关闭"
            labelEn="Closed"
          />
        )
      }
    >
      <DualLabel cn={displayVote.title} className="mb-4" cnClassName="text-base" />

      <div className="space-y-3 mb-4">
        {displayVote.results.map((option, idx) => {
          const pct =
            displayVote.total_votes > 0
              ? Math.round((option.count / displayVote.total_votes) * 100)
              : 0;
          const barWidth =
            maxCount > 0 ? (option.count / maxCount) * 100 : 0;
          const barColor =
            idx === 0
              ? "bg-techCyan"
              : idx === 1
                ? "bg-techGreen"
                : "bg-techMuted";

          return (
            <div
              key={option.option}
              className="relative rounded-lg border border-techBorder bg-techCardSoft p-3"
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <span className="min-w-0 truncate font-semibold text-sm text-techText">
                  {option.option}
                </span>
                <span className="shrink-0 text-sm font-bold text-techCyan">
                  {pct}%
                </span>
              </div>
              <div className="h-2 bg-techCard rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${barColor}`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>
              <p className="text-xs text-techMuted mt-1.5">
                {option.count} 票 / {option.count} vote{option.count !== 1 ? "s" : ""}
              </p>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 mt-3 pt-3 border-t border-techBorder">
        <span className="min-w-0 truncate text-xs text-techMuted">
          {displayVote.total_votes} 票已投
          {displayVote.is_anonymous ? " (匿名)" : ""}
        </span>
        <span className="text-[0.65rem] font-mono uppercase tracking-wider text-techMuted/50 self-end">
          {displayVote.total_votes} vote{displayVote.total_votes !== 1 ? "s" : ""} cast
          {displayVote.is_anonymous ? " (anonymous)" : ""}
        </span>
        {displayVote.status === "open" && onCloseVote && (
          <ActionButton
            variant="danger"
            size="sm"
            icon={closingVote ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
            loading={closingVote}
            onClick={() => onCloseVote(displayVote.vote_id)}
            className="ml-auto"
          >
            Close Vote
          </ActionButton>
        )}
      </div>
    </PanelCard>
  );
}
