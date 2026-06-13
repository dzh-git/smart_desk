import { Trophy, Vote as VoteIcon } from "lucide-react";
import { PanelCard, TechEmptyState } from "./shared";
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
      <PanelCard titleCn="会议结果" titleEn="Meeting Results">
        <TechEmptyState
          icon={<VoteIcon size={20} />}
          titleCn="暂无投票记录"
          titleEn="No Meeting Votes"
          descriptionCn="本次会议暂无投票记录"
          descriptionEn="No vote records for this meeting"
        />
      </PanelCard>
    );
  }

  if (closedVotes.length === 0) {
    return (
      <PanelCard titleCn="会议结果" titleEn="Meeting Results">
        <TechEmptyState
          icon={<VoteIcon size={20} />}
          titleCn="暂无结果"
          titleEn="No Closed Results"
          descriptionCn="投票结束后将显示结果摘要"
          descriptionEn="Results appear after voting ends"
        />
      </PanelCard>
    );
  }

  return (
    <PanelCard
      titleCn="会议结果"
      titleEn="Meeting Results"
      headerRight={
        <span className="text-[0.65rem] font-mono uppercase tracking-wider text-techMuted">
          {closedVotes.length}/{voteResults.length}
        </span>
      }
    >
      <div className="space-y-4">
        {closedVotes.map((vote) => {
          const winner = topOption(vote);
          return (
            <div
              key={vote.vote_id}
              className="rounded-lg border border-techBorder bg-techCardSoft p-3"
            >
              <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-techText">
                    {vote.title}
                  </p>
                  <p className="text-xs text-techMuted">
                    {vote.total_votes} 票 / {vote.total_votes} vote
                    {vote.total_votes !== 1 ? "s" : ""} cast
                  </p>
                </div>
                {winner && (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-techGreen/10 border border-techGreen/30 px-2 py-0.5 text-xs font-medium text-techGreen">
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
                        <span className="min-w-0 truncate font-medium text-techText">
                          {option.option}
                        </span>
                        <span className="shrink-0 text-techMuted">
                          {option.count} / {pct}%
                        </span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-techCard">
                        <div
                          className="h-full rounded-full bg-techCyan"
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
    </PanelCard>
  );
}
