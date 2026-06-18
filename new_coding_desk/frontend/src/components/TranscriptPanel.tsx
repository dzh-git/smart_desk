import { MessageSquare, Loader2, Mic } from "lucide-react";
import { PanelCard, TechEmptyState, SectionHeader, formatTranscriptTime } from "./shared";
import type { TranslationRecord } from "../api/types";

const avatarColors = [
  "bg-techCyan",
  "bg-techGreen",
  "bg-techRose",
  "bg-techAmber",
  "bg-techBlue",
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
  /** Optional two-line caption from backend caption formatter. */
  caption?: {
    previousLine: string;
    currentLine: string;
    mode: string;
  };
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

/**
 * Sort final records oldest-first by created_at, with id as tiebreaker.
 * This ensures the UI always displays history chronologically regardless
 * of the backend's sort order (e.g. newest-first).
 */
function sortFinalsOldestFirst(
  entries: TranslationRecord[],
): TranslationRecord[] {
  return [...entries].sort((a, b) => {
    const ta = new Date(a.created_at).getTime();
    const tb = new Date(b.created_at).getTime();

    // Both parse successfully → oldest first
    if (!isNaN(ta) && !isNaN(tb)) {
      if (ta !== tb) return ta - tb;
    }

    // Fallback: if one or both dates are invalid, still provide a stable
    // order via id ascending so the UI is always deterministic.
    return a.id - b.id;
  });
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
  // Deduplicate finals deterministically, then sort oldest-first
  const dedupedEntries = sortFinalsOldestFirst(deduplicateFinals(entries));

  // Collect utterance_ids that have finals
  const finalUtteranceIds = new Set<string>();
  for (const e of dedupedEntries) {
    if (e.utterance_id) finalUtteranceIds.add(e.utterance_id);
  }

  // Deduplicate interims: per utteranceId keep highest revision, then filter
  const filteredInterims = deduplicateInterims(interims, finalUtteranceIds);

  // Separate interims with and without caption.
  // If caption exists but both previousLine and currentLine are empty,
  // fall back to rendering source_text as a text-only interim row.
  const captionInterims = filteredInterims.filter(
    (i) => i.caption != null && (i.caption.currentLine || i.caption.previousLine),
  );
  const textInterims = filteredInterims.filter(
    (i) => i.caption == null || (!i.caption.currentLine && !i.caption.previousLine),
  );

  const hasInterims = filteredInterims.length > 0;
  const hasEntries = dedupedEntries.length > 0;
  const isEmpty = !loading && !hasEntries && !hasInterims;

  return (
    <PanelCard
      titleCn="会议记录"
      titleEn="Transcript"
      variant={hasInterims ? "active" : "default"}
      headerRight={
        <span className="text-[0.65rem] font-mono uppercase tracking-wider text-techMuted">
          EN / ZH
        </span>
      }
    >
      {loading ? (
        <div className="space-y-3 animate-pulse">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex gap-3">
              <div className="w-8 h-8 rounded-full bg-techCardSoft flex-shrink-0" />
              <div className="flex-1 space-y-2 pt-1">
                <div className="h-3 bg-techCardSoft rounded w-3/4" />
                <div className="h-2.5 bg-techBorder rounded w-1/2" />
              </div>
            </div>
          ))}
        </div>
      ) : isEmpty ? (
        <TechEmptyState
          icon={<MessageSquare size={20} />}
          titleCn="暂无字幕"
          titleEn="No Transcript"
          descriptionCn="实时转写内容将在此显示"
          descriptionEn="Recognized speech appears here in real time"
        />
      ) : (
        <div className="space-y-4 max-h-[40vh] overflow-y-auto pr-1 md:max-h-72">
          {/* Live section header when interims are present */}
          {hasInterims && (
            <SectionHeader
              titleCn="实时识别"
              titleEn="Live Speech"
              icon={<Mic size={14} />}
            />
          )}

          {/* Live caption blocks (interims with caption) */}
          {captionInterims.map((interim) => (
            <LiveCaptionBlock
              key={interim.utteranceId}
              interim={interim}
              speakerName={
                seatNameMap[interim.seatId] ?? `Seat ${interim.seatId}`
              }
            />
          ))}

          {/* Interim rows for interims WITHOUT caption (fallback) */}
          {textInterims.map((interim) => (
            <InterimRow
              key={interim.utteranceId}
              interim={interim}
              speakerName={
                seatNameMap[interim.seatId] ?? `Seat ${interim.seatId}`
              }
            />
          ))}

          {/* History section header when there are entries */}
          {hasEntries && (
            <SectionHeader
              titleCn="历史记录"
              titleEn="History"
              className={hasInterims ? "mt-2 pt-2 border-t border-techBorder" : ""}
            />
          )}

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
    </PanelCard>
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
  const time = formatTranscriptTime(entry.created_at);

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
      data-created-at={entry.created_at}
    >
      <div
        className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-techBg text-xs font-bold ${color}`}
      >
        {initials(speakerName)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="text-xs font-semibold text-techText">
            {speakerName}
          </span>
          <span className="text-[10px] text-techMuted">{time}</span>
          <span
            className="text-[10px] font-medium text-techCyan bg-techCardSoft border border-techCyan/30 rounded-full px-1.5 py-0.5"
            data-testid="transcript-lang-label"
          >
            {langLabel}
          </span>
        </div>
        <p className="text-sm text-techText leading-relaxed" data-testid="transcript-source">
          {entry.source_text}
        </p>
        <p className="text-xs text-techMuted mt-1 leading-relaxed border-l-2 border-techBorder pl-2" data-testid="transcript-target">
          {entry.translated_text}
        </p>
      </div>
    </div>
  );
}

// ── Live Caption Block (two-line subtitle display) ────────────────────────────

function LiveCaptionBlock({
  interim,
  speakerName,
}: {
  interim: InterimDisplayEntry;
  speakerName: string;
}) {
  if (!interim.caption) return null;

  const caption = interim.caption;

  return (
    <div
      data-testid="live-caption"
      data-utterance-id={interim.utteranceId}
      data-seat-id={interim.seatId}
      data-revision={interim.revision}
      className="bg-techCardSoft border border-techCyan/40 rounded-lg p-3 shadow-cyan-glow"
    >
      <div className="flex items-baseline gap-2 mb-1.5">
        <span className="text-xs font-semibold text-techCyan">
          {speakerName}
        </span>
        <Loader2 size={10} className="animate-spin text-techCyan" />
        <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techCyan/50 ml-auto">
          实时 / Live
        </span>
      </div>
      <div
        data-testid="live-caption-previous"
        className="min-h-[1.25rem] max-h-[1.25rem] overflow-hidden break-words text-sm text-techMuted leading-snug"
      >
        {caption.previousLine}
      </div>
      <div
        data-testid="live-caption-current"
        className="min-h-[1.5rem] max-h-[1.5rem] overflow-hidden break-words text-base text-techText font-medium leading-snug"
      >
        {caption.currentLine}
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
      className="flex gap-3 opacity-70"
      data-testid="transcript-interim"
      data-utterance-id={interim.utteranceId}
      data-seat-id={interim.seatId}
      data-revision={interim.revision}
    >
      <div
        className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-techBg text-xs font-bold ${color}`}
      >
        {initials(speakerName)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="text-xs font-semibold text-techText">
            {speakerName}
          </span>
          <Loader2
            size={10}
            className="animate-spin text-techCyan"
          />
          <span
            className="text-[10px] font-medium text-techCyan bg-techCardSoft border border-techCyan/30 rounded-full px-1.5 py-0.5"
            data-testid="transcript-lang-label"
          >
            {langLabel}
          </span>
        </div>
        <p className="text-sm text-techMuted leading-relaxed italic" data-testid="transcript-source">
          {interim.sourceText}
        </p>
        {interim.translatedText && (
          <p className="text-xs text-techMuted/70 mt-1 leading-relaxed border-l-2 border-techCyan/30 pl-2 italic" data-testid="transcript-target">
            {interim.translatedText}
          </p>
        )}
      </div>
    </div>
  );
}
