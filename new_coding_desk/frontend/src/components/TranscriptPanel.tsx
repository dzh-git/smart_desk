import { MessageSquare } from "lucide-react";
import { SectionCard, EmptyState, LoadingState } from "./shared";
import type { TranslationRecord } from "../api/types";

const avatarColors = [
  "bg-sky-600",
  "bg-teal-600",
  "bg-rose-600",
  "bg-amber-600",
  "bg-emerald-600",
  "bg-cyan-700",
  "bg-blue-700",
  "bg-orange-600",
  "bg-slate-600",
  "bg-green-700",
];

function initials(name: string) {
  return name
    .split(" ")
    .slice(0, 2)
    .map((n) => n[0])
    .join("");
}

interface TranscriptPanelProps {
  entries: TranslationRecord[];
  /** Mapping seat_id → speaker name */
  seatNameMap: Record<number, string>;
  loading?: boolean;
}

export function TranscriptPanel({
  entries,
  seatNameMap,
  loading = false,
}: TranscriptPanelProps) {
  return (
    <SectionCard
      title="Bilingual Transcript"
      headerRight={
        <span className="text-xs text-slate-400 font-medium">EN / 中文</span>
      }
    >
      {loading ? (
        <LoadingState rows={3} />
      ) : entries.length === 0 ? (
        <EmptyState
          icon={<MessageSquare size={20} />}
          title="No transcript yet"
          description="Recognized speech will appear here in real time."
        />
      ) : (
        <div className="space-y-4 max-h-72 overflow-y-auto pr-1">
          {entries.map((entry) => (
            <TranscriptRow
              key={entry.id}
              entry={entry}
              speakerName={
                seatNameMap[entry.seat_id] ?? `Seat ${entry.seat_id}`
              }
            />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function TranscriptRow({
  entry,
  speakerName,
}: {
  entry: TranslationRecord;
  speakerName: string;
}) {
  const color = avatarColors[(entry.seat_id - 1) % avatarColors.length];
  const time = new Date(entry.created_at).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });

  const langLabel =
    entry.source_lang.toUpperCase() === "EN" ? "EN" : "中文";

  return (
    <div className="flex gap-3">
      <div
        className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-white text-xs font-bold ${color}`}
      >
        {initials(speakerName)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="text-xs font-semibold text-slate-700">
            {speakerName}
          </span>
          <span className="text-[10px] text-slate-400">{time}</span>
          <span className="text-[10px] font-medium text-slate-500 bg-slate-100 border border-slate-200 rounded-full px-1.5 py-0.5">
            {langLabel}
          </span>
        </div>
        <p className="text-sm text-slate-700 leading-relaxed">
          {entry.source_text}
        </p>
        <p className="text-xs text-slate-500 mt-1 leading-relaxed border-l-2 border-slate-200 pl-2">
          {entry.translated_text}
        </p>
      </div>
    </div>
  );
}
