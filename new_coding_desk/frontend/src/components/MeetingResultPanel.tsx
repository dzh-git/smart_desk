import { Trophy, Vote as VoteIcon } from "lucide-react";
import { EmptyState, SectionCard } from "./shared";
import type { VoteOptionStat, VoteStatistics } from "../api/types";

interface MeetingResultPanelProps {
  voteResults: VoteStatistics[];
}

function percentage(option: VoteOptionStat, totalVotes: number): number {
  if (totalVotes <= 0) return 0;
  return Math.round((option.count / totalVotes) * 100);
}

function topOption(vote: VoteStatistics): VoteOptionStat | null {
  if (vote.results.length === 0) return null;
  return [...vote.results].sort((a, b) => b.count - a.count)[0];
}

export function MeetingResultPanel({ voteResults }: MeetingResultPanelProps) {
  const closedVotes = voteResults.filter((vote) => vote.status === "closed");

  if (voteResults.length === 0) {
    return (
      <SectionCard title="Meeting Results">
        <EmptyState
          icon={<VoteIcon size={20} />}
          title="No meeting votes"
          description="This meeting has no vote records yet."
        />
      </SectionCard>
    );
  }

  if (closedVotes.length === 0) {
    return (
      <SectionCard title="Meeting Results">
        <EmptyState
          icon={<VoteIcon size={20} />}
          title="No closed vote results"
          description="Closed vote summaries will appear here after voting ends."
        />
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="Meeting Results"
      headerRight={
        <span className="text-xs font-medium text-slate-400">
          {closedVotes.length}/{voteResults.length} closed
        </span>
      }
    >
      <div className="space-y-4">
        {closedVotes.map((vote) => {
          const winner = topOption(vote);
          return (
            <div
              key={vote.vote_id}
              className="rounded-xl border border-slate-200 bg-slate-50 p-3"
            >
              <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-800">
                    {vote.title}
                  </p>
                  <p className="text-xs text-slate-500">
                    {vote.total_votes} vote
                    {vote.total_votes !== 1 ? "s" : ""} cast
                  </p>
                </div>
                {winner && (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                    <Trophy size={12} />
                    Top: {winner.option}
                  </span>
                )}
              </div>

              <div className="space-y-2">
                {vote.results.map((option) => {
                  const pct = percentage(option, vote.total_votes);
                  return (
                    <div key={option.option}>
                      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                        <span className="min-w-0 truncate font-medium text-slate-700">
                          {option.option}
                        </span>
                        <span className="shrink-0 text-slate-500">
                          {option.count} / {pct}%
                        </span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-white">
                        <div
                          className="h-full rounded-full bg-sky-500"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}
