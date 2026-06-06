import { MessageSquare, Loader2 } from "lucide-react";
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

// ── Interim entry type (from WS translation_interim events) ─────────────────

export interface InterimDisplayEntry {
  utteranceId: string;
  seatId: number;
  revision: number;
  sourceLang: string;
  targetLang: string;
  sourceText: string;
  translatedText: string;
}

// ── Props ──────────────────────────────────────────────────────────────────

interface TranscriptPanelProps {
  /** Persisted final translation records from GET /api/translations. */
  entries: TranslationRecord[];
  /** Live interim subtitles keyed by utterance_id. */
  interims?: InterimDisplayEntry[];
  /** Mapping seat_id -> speaker name. */
  seatNameMap: Record<number, string>;
  /** True while translations are being fetched for the first time. */
  loading?: boolean;
}

// ── Deduplication helpers ──────────────────────────────────────────────────

/** Deduplicate finals deterministically:
 *  1. By translation id — keep first occurrence.
 *  2. Within id-deduped set, group by utterance_id.
 *     - Entries WITH utterance_id → keep the one with latest created_at;
 *       if same created_at, keep the one with max id.
 *     - Entries WITHOUT utterance_id → keep all (can't dedup).
 *  3. Order: no-utterance entries first (stable), then one per utterance_id.
 */
function deduplicateFinals(entries: TranslationRecord[]): TranslationRecord[] {
  // 1. Dedup by translation id (keep first)
  const seenIds = new Set<number>();
  const idDeduped: TranslationRecord[] = [];
  for (const e of entries) {
    if (!seenIds.has(e.id)) {
      seenIds.add(e.id);
      idDeduped.push(e);
    }
  }

  // 2. Separate entries with and without utterance_id
  const noUtterance: TranslationRecord[] = [];
  const byUtterance = new Map<string, TranslationRecord>();
  for (const e of idDeduped) {
    if (e.utterance_id) {
      const existing = byUtterance.get(e.utterance_id);
      if (!existing) {
        byUtterance.set(e.utterance_id, e);
      } else {
        // Keep latest created_at; if same, keep max id
        const existingTime = new Date(existing.created_at).getTime();
        const entryTime = new Date(e.created_at).getTime();
        if (
          entryTime > existingTime ||
          (entryTime === existingTime && e.id > existing.id)
        ) {
          byUtterance.set(e.utterance_id, e);
        }
      }
    } else {
      noUtterance.push(e);
    }
  }

  return [...noUtterance, ...byUtterance.values()];
}

/** Deduplicate interims: per utteranceId keep the entry with highest revision;
 *  if same revision, keep the last one in the array.
 */
function deduplicateInterims(
  interims: InterimDisplayEntry[],
  finalUtteranceIds: Set<string>,
): InterimDisplayEntry[] {
  const byId = new Map<string, InterimDisplayEntry>();
  for (const i of interims) {
    const existing = byId.get(i.utteranceId);
    if (!existing) {
      byId.set(i.utteranceId, i);
    } else {
      if (
        i.revision > existing.revision ||
        (i.revision === existing.revision)
        // same revision → keep the LATER one in array order
      ) {
        byId.set(i.utteranceId, i);
      }
    }
  }

  // Filter out interims whose utterance_id already has a final entry
  const result: InterimDisplayEntry[] = [];
  for (const entry of byId.values()) {
    if (!finalUtteranceIds.has(entry.utteranceId)) {
      result.push(entry);
    }
  }
  return result;
}

// ── Component ──────────────────────────────────────────────────────────────

export function TranscriptPanel({
  entries,
  interims = [],
  seatNameMap,
  loading = false,
}: TranscriptPanelProps) {
  // Deduplicate finals deterministically
  const dedupedEntries = deduplicateFinals(entries);

  // Collect utterance_ids that have finals
  const finalUtteranceIds = new Set<string>();
  for (const e of dedupedEntries) {
    if (e.utterance_id) finalUtteranceIds.add(e.utterance_id);
  }

  // Deduplicate interims: per utteranceId keep highest revision, then filter
  const filteredInterims = deduplicateInterims(interims, finalUtteranceIds);

  const hasInterims = filteredInterims.length > 0;
  const hasEntries = dedupedEntries.length > 0;
  const isEmpty = !loading && !hasEntries && !hasInterims;

  return (
    <SectionCard
      title="Bilingual Transcript"
      headerRight={
        <span className="text-xs text-slate-400 font-medium">EN / ZH</span>
      }
    >
      {loading ? (
        <LoadingState rows={3} />
      ) : isEmpty ? (
        <EmptyState
          icon={<MessageSquare size={20} />}
          title="No transcript yet"
          description="Recognized speech will appear here in real time."
        />
      ) : (
        <div className="space-y-4 max-h-72 overflow-y-auto pr-1">
          {/* Interim entries (live, not persisted) */}
          {filteredInterims.map((interim) => (
            <InterimRow
              key={interim.utteranceId}
              interim={interim}
              speakerName={
                seatNameMap[interim.seatId] ?? `Seat ${interim.seatId}`
              }
            />
          ))}

          {/* Final entries (persisted) */}
          {dedupedEntries.map((entry) => (
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

// ── Final Transcript Row ───────────────────────────────────────────────────

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
    entry.source_lang.toUpperCase() === "EN" ? "EN" : "ZH";

  const utteranceId = entry.utterance_id ?? null;

  return (
    <div
      className="flex gap-3"
      data-testid="transcript-final"
      data-utterance-id={utteranceId ?? ""}
      data-seat-id={entry.seat_id}
      data-translation-id={entry.id}
    >
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
          <span
            className="text-[10px] font-medium text-slate-500 bg-slate-100 border border-slate-200 rounded-full px-1.5 py-0.5"
            data-testid="transcript-lang-label"
          >
            {langLabel}
          </span>
        </div>
        <p className="text-sm text-slate-700 leading-relaxed" data-testid="transcript-source">
          {entry.source_text}
        </p>
        <p className="text-xs text-slate-500 mt-1 leading-relaxed border-l-2 border-slate-200 pl-2" data-testid="transcript-target">
          {entry.translated_text}
        </p>
      </div>
    </div>
  );
}

// ── Interim Row (live subtitle, not persisted) ──────────────────────────────

function InterimRow({
  interim,
  speakerName,
}: {
  interim: InterimDisplayEntry;
  speakerName: string;
}) {
  const color = avatarColors[(interim.seatId - 1) % avatarColors.length];

  const langLabel =
    interim.sourceLang.toUpperCase() === "EN" ? "EN" : "ZH";

  return (
    <div
      className="flex gap-3 opacity-80"
      data-testid="transcript-interim"
      data-utterance-id={interim.utteranceId}
      data-seat-id={interim.seatId}
      data-revision={interim.revision}
    >
      <div
        className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-white text-xs font-bold ${color}`}
      >
        {initials(speakerName)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="text-xs font-semibold text-slate-600">
            {speakerName}
          </span>
          <Loader2
            size={10}
            className="animate-spin text-sky-400"
          />
          <span
            className="text-[10px] font-medium text-sky-500 bg-sky-50 border border-sky-200 rounded-full px-1.5 py-0.5"
            data-testid="transcript-lang-label"
          >
            {langLabel}
          </span>
        </div>
        <p className="text-sm text-slate-500 leading-relaxed italic" data-testid="transcript-source">
          {interim.sourceText}
        </p>
        {interim.translatedText && (
          <p className="text-xs text-slate-400 mt-1 leading-relaxed border-l-2 border-sky-200 pl-2 italic" data-testid="transcript-target">
            {interim.translatedText}
          </p>
        )}
      </div>
    </div>
  );
}
