import { Vote as VoteIcon, AlertCircle, RefreshCw, CheckCircle2, Loader2 } from "lucide-react";
import { SectionCard, EmptyState } from "./shared";
import type { VoteStatistics } from "../api/types";

interface VotePanelProps {
  vote: VoteStatistics | null;
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
  hasActiveVote = false,
  voteStatsError = null,
  onRetryStats,
  onCloseVote,
  closingVote = false,
}: VotePanelProps) {
  // ── Vote exists but statistics failed ──────────────────────────────────
  if (hasActiveVote && !vote && voteStatsError) {
    return (
      <SectionCard title="Active Vote">
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <div className="w-12 h-12 rounded-full bg-amber-50 border-2 border-amber-200 flex items-center justify-center text-amber-500 mb-3">
            <AlertCircle size={20} />
          </div>
          <p className="text-sm font-semibold text-slate-800 mb-1">
            Vote statistics unavailable
          </p>
          <p className="text-xs text-slate-500 mb-4 max-w-xs">
            {voteStatsError}
          </p>
          {onRetryStats && (
            <button
              onClick={onRetryStats}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-600 border border-sky-200 rounded-lg px-3 py-1.5 hover:bg-sky-50 transition-colors"
            >
              <RefreshCw size={12} />
              Retry
            </button>
          )}
        </div>
      </SectionCard>
    );
  }

  // ── No vote ────────────────────────────────────────────────────────────
  if (!vote) {
    return (
      <SectionCard title="Active Vote">
        <EmptyState
          icon={<VoteIcon size={20} />}
          title="No vote in progress"
          description="Votes will appear here when initiated by the chair."
        />
      </SectionCard>
    );
  }

  // ── Vote with statistics ───────────────────────────────────────────────
  const maxCount = Math.max(...vote.results.map((o) => o.count), 1);

  return (
    <SectionCard
      title="Active Vote"
      headerRight={
        <span
          className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
            vote.status === "open"
              ? "bg-sky-100 text-sky-700"
              : "bg-slate-100 text-slate-500"
          }`}
        >
          {vote.status === "open" ? "Open" : "Closed"}
        </span>
      }
    >
      <p className="font-semibold text-slate-800 text-sm mb-3">
        {vote.title}
      </p>

      <div className="space-y-3 mb-4">
        {vote.results.map((option, idx) => {
          const pct =
            vote.total_votes > 0
              ? Math.round((option.count / vote.total_votes) * 100)
              : 0;
          const barWidth =
            maxCount > 0 ? (option.count / maxCount) * 100 : 0;
          const barColor =
            idx === 0
              ? "bg-emerald-500"
              : idx === 1
                ? "bg-rose-500"
                : "bg-slate-400";

          return (
            <div
              key={option.option}
              className="relative rounded-xl border border-slate-200 p-2.5"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold text-sm text-slate-800">
                  {option.option}
                </span>
                <span className="text-sm font-bold text-slate-700">
                  {pct}%
                </span>
              </div>
              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${barColor}`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>
              <p className="text-xs text-slate-400 mt-1.5">
                {option.count} vote{option.count !== 1 ? "s" : ""}
              </p>
            </div>
          );
        })}
      </div>

      <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-100">
        <p className="text-xs text-slate-400">
          {vote.total_votes} vote{vote.total_votes !== 1 ? "s" : ""} cast
          {vote.is_anonymous ? " (anonymous)" : ""}
        </p>
        {vote.status === "open" && onCloseVote && (
          <button
            onClick={() => onCloseVote(vote.vote_id)}
            disabled={closingVote}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-rose-600 bg-white border border-rose-200 rounded-lg px-3 py-1.5 hover:bg-rose-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {closingVote ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <CheckCircle2 size={12} />
            )}
            Close Vote
          </button>
        )}
      </div>
    </SectionCard>
  );
}
