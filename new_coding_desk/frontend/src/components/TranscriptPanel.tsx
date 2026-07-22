import { memo, useEffect, useMemo, useRef } from "react";
import { MessageSquare, Loader2, Mic } from "lucide-react";
import { PanelCard, TechEmptyState, SectionHeader, formatTranscriptTime } from "./shared";
import type { TranslationRecord } from "../api/types";
import type { PendingTranslation } from "../types";
import type { LiveLyricSentence } from "../types";
import { trace } from "../audio/speechTrace";

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
  /** Exact two-line source window represented by translatedText. */
  translationSourceText?: string;
  /** Revision of the newest translated prefix; source recognition may be newer. */
  translationRevision?: number;
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
  /** Latest sentence-final pair retained in the live subtitle area. */
  liveFinal?: TranslationRecord | null;
  /** Live interim subtitles keyed by utterance_id. */
  interims?: InterimDisplayEntry[];
  /** Sentence-level lyric history per seat; fixed viewport scrolls old pairs. */
  lyrics?: LiveLyricSentence[];
  /** Realtime text already rolled into history while translation is pending. */
  pendingFinals?: PendingTranslation[];
  /** Mapping seat_id -> speaker name. */
  seatNameMap: Record<number, string>;
  /** True while translations are being fetched for the first time. */
  loading?: boolean;
  /** Keep the live speech area mounted while an active meeting is running. */
  liveEnabled?: boolean;
  /** True while the meeting WebSocket is restoring its connection. */
  liveReconnecting?: boolean;
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

const PARAGRAPH_GAP_MS = 30_000;

function groupFinals(entries: TranslationRecord[]): TranslationRecord[][] {
  const groups: TranslationRecord[][] = [];
  for (const entry of entries) {
    const group = groups.length ? groups[groups.length - 1] : undefined;
    const previous = group?.length ? group[group.length - 1] : undefined;
    if (group && previous) {
      const previousTime = new Date(previous.created_at).getTime();
      const entryTime = new Date(entry.created_at).getTime();
      const gap = entryTime - previousTime;
      const canMerge =
        previous.seat_id === entry.seat_id &&
        previous.source_lang === entry.source_lang &&
        previous.target_lang === entry.target_lang &&
        Number.isFinite(gap) &&
        gap >= 0 &&
        gap <= PARAGRAPH_GAP_MS;
      if (canMerge) {
        group.push(entry);
        continue;
      }
    }
    groups.push([entry]);
  }
  return groups;
}

function joinSentences(texts: string[], language: string): string {
  const clean = texts.map((text) => text.trim()).filter(Boolean);
  return language.toLowerCase() === "zh" ? clean.join("") : clean.join(" ");
}

function isUnavailableTranslation(text: string): boolean {
  const normalized = text.trim().toLowerCase();
  return (
    !normalized ||
    normalized.startsWith("[translation not available") ||
    normalized.startsWith("[translation failed") ||
    normalized.startsWith("[translation unavailable")
  );
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
  liveFinal = null,
  interims = [],
  lyrics = [],
  pendingFinals = [],
  seatNameMap,
  loading = false,
  liveEnabled = false,
  liveReconnecting = false,
}: TranscriptPanelProps) {
  // Deduplicate finals deterministically, then sort oldest-first
  const dedupedEntries = useMemo(
    () => sortFinalsOldestFirst(deduplicateFinals(entries)),
    [entries],
  );
  const visibleHistoryEntries = useMemo(
    () => dedupedEntries.filter((entry) => {
      if (!liveEnabled || !liveFinal) return true;
      if (entry.id === liveFinal.id) return false;
      return !(
        entry.utterance_id
        && liveFinal.utterance_id
        && entry.utterance_id === liveFinal.utterance_id
      );
    }),
    [dedupedEntries, liveEnabled, liveFinal],
  );
  const finalGroups = useMemo(
    () => groupFinals(visibleHistoryEntries),
    [visibleHistoryEntries],
  );

  // Collect utterance_ids that have finals
  const finalUtteranceIds = useMemo(() => {
    const ids = new Set<string>();
    for (const entry of dedupedEntries) {
      if (entry.utterance_id) ids.add(entry.utterance_id);
    }
    return ids;
  }, [dedupedEntries]);
  const filteredPendingFinals = useMemo(
    () => pendingFinals.filter(
      (entry) => !finalUtteranceIds.has(entry.utteranceId),
    ),
    [pendingFinals, finalUtteranceIds],
  );

  // Deduplicate interims: per utteranceId keep highest revision, then filter
  const filteredInterims = useMemo(
    () => deduplicateInterims(interims, finalUtteranceIds),
    [interims, finalUtteranceIds],
  );
  const lyricGroups = useMemo(() => {
    const bySeat = new Map<number, LiveLyricSentence[]>();
    for (const sentence of lyrics) {
      const group = bySeat.get(sentence.seatId) ?? [];
      group.push(sentence);
      bySeat.set(sentence.seatId, group);
    }
    return Array.from(bySeat.entries()).map(([seatId, sentences]) => ({
      seatId,
      sentences: [...sentences]
        .sort((a, b) => a.sentenceSequence - b.sentenceSequence),
    }));
  }, [lyrics]);

  // Caption entries with visible lines use the two-line live box. Empty
  // captions and entries without caption use the fallback row, whose active
  // meeting variant keeps the same fixed-height shell.
  const captionInterims = filteredInterims.filter(
    (i) => i.caption != null && (i.caption.currentLine || i.caption.previousLine),
  );
  const textInterims = filteredInterims.filter(
    (i) => i.caption == null || (!i.caption.currentLine && !i.caption.previousLine),
  );

  const hasInterims = filteredInterims.length > 0;
  const hasLyrics = lyricGroups.length > 0;
  const hasEntries = visibleHistoryEntries.length > 0;
  const hasPendingFinals = filteredPendingFinals.length > 0;
  const isEmpty = !loading && !hasEntries && !hasPendingFinals && !hasInterims && !hasLyrics && !liveEnabled;

  return (
    <PanelCard
      titleCn="会议记录"
      titleEn="Transcript"
      variant={hasInterims || hasLyrics ? "active" : "default"}
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
          {/* Keep the live section mounted throughout an active meeting. */}
          {(liveEnabled || hasInterims || hasLyrics || liveFinal) && (
            <SectionHeader
              titleCn="实时识别"
              titleEn="Live Speech"
              icon={<Mic size={14} />}
            />
          )}

          {liveEnabled && !liveFinal && !hasLyrics && captionInterims.length === 0 && textInterims.length === 0 && (
            <LiveCaptionPlaceholder reconnecting={liveReconnecting} />
          )}

          {liveEnabled && liveFinal && !hasLyrics && captionInterims.length === 0 && textInterims.length === 0 && (
            <LiveFinalBlock
              entry={liveFinal}
              speakerName={seatNameMap[liveFinal.seat_id] ?? `Seat ${liveFinal.seat_id}`}
            />
          )}

          {lyricGroups.map(({ seatId, sentences }) => (
            <LiveLyricsBlock
              key={`lyrics-seat-${seatId}`}
              sentences={sentences}
              speakerName={seatNameMap[seatId] ?? `Seat ${seatId}`}
            />
          ))}

          {/* Live caption blocks (interims with caption) */}
          {!hasLyrics && captionInterims.map((interim) => (
            <LiveCaptionBlock
              key={`seat-${interim.seatId}`}
              interim={interim}
              speakerName={
                seatNameMap[interim.seatId] ?? `Seat ${interim.seatId}`
              }
            />
          ))}

          {/* Keep fallback interims in a fixed-height shell during a meeting. */}
          {!hasLyrics && textInterims.map((interim) => (
            <InterimRow
              key={interim.utteranceId}
              interim={interim}
              speakerName={
                seatNameMap[interim.seatId] ?? `Seat ${interim.seatId}`
              }
              stable={liveEnabled}
            />
          ))}

          {/* History section header when there are entries */}
          {(hasEntries || hasPendingFinals) && (
            <SectionHeader
              titleCn="历史记录"
              titleEn="History"
              className={hasInterims || hasLyrics ? "mt-2 pt-2 border-t border-techBorder" : ""}
            />
          )}

          {/* Final entries (persisted) */}
          {finalGroups.map((group) => (
            <TranscriptGroupRow
              key={group.map((entry) => entry.id).join("-")}
              entries={group}
              speakerName={
                seatNameMap[group[0].seat_id] ?? `Seat ${group[0].seat_id}`
              }
            />
          ))}

          {filteredPendingFinals.map((pending) => (
            <PendingFinalRow
              key={pending.utteranceId}
              pending={pending}
              speakerName={
                seatNameMap[pending.seatId] ?? `Seat ${pending.seatId}`
              }
            />
          ))}
        </div>
      )}
    </PanelCard>
  );
}

function LiveFinalBlock({
  entry,
  speakerName,
}: {
  entry: TranslationRecord;
  speakerName: string;
}) {
  const translated = !isUnavailableTranslation(entry.translated_text)
    ? entry.translated_text
    : "";
  return (
    <div
      className="bg-techCardSoft border border-techGreen/40 rounded-lg p-3 min-h-[7.25rem]"
      data-testid="transcript-final"
      data-utterance-id={entry.utterance_id ?? ""}
      data-seat-id={entry.seat_id}
      data-translation-id={entry.id}
    >
      <div data-testid="live-final-translation">
        <div className="flex items-baseline gap-2 mb-1.5">
          <span className="text-xs font-semibold text-techGreen">{speakerName}</span>
          <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techGreen/70 ml-auto">
            {entry.source_lang.toUpperCase()} → {entry.target_lang.toUpperCase()} · 最终译文
          </span>
        </div>
        <p className="text-sm text-techText leading-relaxed" data-testid="live-final-source">
          {entry.source_text}
        </p>
        {translated ? (
          <p className="text-sm text-techCyan mt-2 leading-relaxed border-l-2 border-techCyan/50 pl-2" data-testid="live-final-target">
            {translated}
          </p>
        ) : (
          <p className="text-xs text-techAmber mt-2" data-testid="live-final-target-unavailable">
            翻译模型不可用{entry.translation_error ? `：${entry.translation_error}` : ""}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Final Transcript Row ───────────────────────────────────────────────────

function PendingFinalRow({
  pending,
  speakerName,
}: {
  pending: PendingTranslation;
  speakerName: string;
}) {
  const color = avatarColors[(pending.seatId - 1) % avatarColors.length];
  return (
    <div
      className="flex gap-3"
      data-testid="transcript-pending-final"
      data-utterance-id={pending.utteranceId}
      data-seat-id={pending.seatId}
    >
      <div
        className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-techBg text-xs font-bold ${color}`}
      >
        {initials(speakerName)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="text-xs font-semibold text-techText">{speakerName}</span>
          <Loader2 size={10} className="animate-spin text-techAmber" />
          <span className="text-[10px] text-techAmber">正在翻译… / Translating…</span>
        </div>
        <p className="text-sm text-techText leading-relaxed" data-testid="transcript-source">
          {pending.sourceText}
        </p>
      </div>
    </div>
  );
}

const TranscriptGroupRow = memo(function TranscriptGroupRow({
  entries,
  speakerName,
}: {
  entries: TranslationRecord[];
  speakerName: string;
}) {
  const entry = entries[0];
  const color = avatarColors[(entry.seat_id - 1) % avatarColors.length];
  const time = formatTranscriptTime(entry.created_at);

  const langLabel = `${entry.source_lang.toUpperCase()} → ${entry.target_lang.toUpperCase()}`;

  const utteranceIds = entries
    .map((item) => item.utterance_id)
    .filter((value): value is string => Boolean(value));
  const sourceText = joinSentences(
    entries.map((item) => item.source_text),
    entry.source_lang,
  );
  const validTranslations = entries
    .map((item) => item.translated_text)
    .filter((text) => !isUnavailableTranslation(text));
  const translatedText = joinSentences(validTranslations, entry.target_lang);

  return (
    <div
      className="flex gap-3"
      data-testid="transcript-final"
      data-utterance-id={utteranceIds.join(",")}
      data-seat-id={entry.seat_id}
      data-translation-id={entry.id}
      data-translation-ids={entries.map((item) => item.id).join(",")}
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
          {sourceText}
        </p>
        {translatedText ? (
          <p className="text-xs text-techMuted mt-1 leading-relaxed border-l-2 border-techBorder pl-2" data-testid="transcript-target">
            {translatedText}
          </p>
        ) : (
          <p className="text-xs text-techAmber mt-1" data-testid="transcript-target-unavailable">
            翻译模型不可用{entry.translation_error ? `：${entry.translation_error}` : ""}
          </p>
        )}
      </div>
    </div>
  );
});

// ── Sentence-paired lyric display ────────────────────────────────────────────

function LiveLyricsBlock({
  sentences,
  speakerName,
}: {
  sentences: LiveLyricSentence[];
  speakerName: string;
}) {
  const renderedStatesRef = useRef<Set<string>>(new Set());
  const lyricViewportRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    for (const sentence of sentences) {
      if (sentence.translationStatus === "forming") continue;
      const stateKey = [
        sentence.sentenceId,
        sentence.revision,
        sentence.translationStatus,
      ].join(":");
      if (renderedStatesRef.current.has(stateKey)) continue;
      renderedStatesRef.current.add(stateKey);
      trace(
        sentence.translationStatus === "pending"
          ? "frontend_sentence_pending_rendered_at"
          : "frontend_sentence_translation_rendered_at",
        {
        utteranceId: sentence.utteranceId,
        sentenceId: sentence.sentenceId,
        sentenceSequence: sentence.sentenceSequence,
        revision: sentence.revision,
        seatId: sentence.seatId,
        translationStatus: sentence.translationStatus,
        },
      );
    }
  }, [sentences]);

  useEffect(() => {
    const viewport = lyricViewportRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [sentences]);

  const latest = sentences[sentences.length - 1];
  const busy = latest?.translationStatus === "forming"
    || latest?.translationStatus === "pending";
  return (
    <div
      data-testid="live-lyrics"
      data-seat-id={latest?.seatId}
      className="bg-techCardSoft border border-techCyan/40 rounded-lg p-3 shadow-cyan-glow h-[15rem] flex flex-col"
    >
      <div className="flex items-baseline gap-2 mb-2">
        <span className="text-xs font-semibold text-techCyan">{speakerName}</span>
        {busy && <Loader2 size={10} className="animate-spin text-techCyan" />}
        <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techCyan/50 ml-auto">
          逐句 / LYRICS
        </span>
      </div>
      <div
        ref={lyricViewportRef}
        className="space-y-2 flex flex-col justify-end flex-1 min-h-0 overflow-y-auto pr-1"
        data-testid="live-lyric-pairs"
      >
        {sentences.map((sentence, index) => {
          const current = index === sentences.length - 1;
          return (
            <div
              key={sentence.sentenceId}
              data-testid="live-lyric-pair"
              data-sentence-id={sentence.sentenceId}
              data-sentence-sequence={sentence.sentenceSequence}
              className={current ? "opacity-100" : "opacity-55"}
            >
              <LiveLyricText
                data-testid="live-lyric-source"
                className={`leading-snug ${
                  current
                    ? "text-base text-techText font-medium"
                    : "text-sm text-techMuted"
                }`}
                text={sentence.sourceText}
                language={sentence.sourceLang}
              />
              <div className="min-h-[1.1rem] mt-0.5 border-l-2 border-techCyan/45 pl-2">
                {sentence.translationStatus === "pending" ? (
                  <p className="text-xs text-techMuted/70" data-testid="live-lyric-pending">
                    {sentence.recognitionStatus === "correcting"
                      ? "识别校正中… / Correcting speech…"
                      : "正在翻译… / Translating…"}
                  </p>
                ) : sentence.translationStatus === "unavailable" ? (
                  <p className="text-xs text-techRose" data-testid="live-lyric-unavailable">
                    译文不可用 / Translation unavailable
                  </p>
                ) : sentence.translationStatus === "ok" ? (
                  <LiveLyricText
                    className="text-sm text-techCyan leading-snug"
                    data-testid="live-lyric-translation"
                    text={sentence.translatedText}
                    language={sentence.targetLang}
                  />
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LiveLyricText({
  text,
  className,
  language,
  ...props
}: {
  text: string;
  className: string;
  language: string;
  "data-testid": string;
}) {
  return (
    <div
      {...props}
      className={`${className} whitespace-normal`}
      lang={language === "en" ? "en" : language === "zh" ? "zh-CN" : undefined}
      style={{
        overflowWrap: "normal",
        wordBreak: "normal",
        hyphens: "none",
      }}
    >
      {text}
    </div>
  );
}

// ── Legacy Live Caption Block (protocol compatibility) ───────────────────────

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
      className="bg-techCardSoft border border-techCyan/40 rounded-lg p-3 shadow-cyan-glow min-h-[9rem]"
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
      {interim.translatedText ? (
        <p
          className="mt-2 border-l-2 border-techCyan/50 pl-2 text-sm text-techCyan leading-snug overflow-hidden"
          data-testid="live-caption-translation"
          data-window-lines="2"
          style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}
        >
          {interim.translatedText}
        </p>
      ) : (
        <p className="mt-2 text-xs text-techMuted/70" data-testid="live-caption-translation-pending">
          正在生成实时译文… / Translating live speech…
        </p>
      )}
    </div>
  );
}

function LiveCaptionPlaceholder({ reconnecting }: { reconnecting: boolean }) {
  return (
    <div
      data-testid="live-caption-placeholder"
      className="bg-techCardSoft border border-techCyan/30 rounded-lg p-3 min-h-[7.25rem]"
    >
      <span className="sr-only">暂无字幕</span>
      <div className="flex items-baseline gap-2 mb-1.5">
        <span className="text-xs font-semibold text-techMuted">
          {reconnecting
            ? "实时识别连接恢复中…… / Reconnecting live speech…"
            : "正在监听，等待有效语音…… / Listening for speech…"}
        </span>
        <span className="text-[0.6rem] font-mono uppercase tracking-wider text-techMuted/60 ml-auto">
          实时 / Live
        </span>
      </div>
      <div
        data-testid="live-caption-previous"
        className="min-h-[1.25rem] max-h-[1.25rem] overflow-hidden break-words text-sm text-techMuted leading-snug"
      />
      <div
        data-testid="live-caption-current"
        className="min-h-[1.5rem] max-h-[1.5rem] overflow-hidden break-words text-base text-techMuted/70 font-medium leading-snug"
      />
    </div>
  );
}

// ── Interim Row (live subtitle, not persisted) ──────────────────────────────

function InterimRow({
  interim,
  speakerName,
  stable = false,
}: {
  interim: InterimDisplayEntry;
  speakerName: string;
  stable?: boolean;
}) {
  const color = avatarColors[(interim.seatId - 1) % avatarColors.length];

  const langLabel = interim.sourceLang === "unknown" ? "识别中" : interim.sourceLang.toUpperCase();

  return (
    <div
      className={
        stable
          ? "flex gap-3 bg-techCardSoft border border-techCyan/30 rounded-lg p-3 min-h-[7.25rem]"
          : "flex gap-3 opacity-70"
      }
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
