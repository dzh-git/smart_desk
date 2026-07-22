import type { LiveLyricSentence } from "../types";

export type LiveLyricMap = Record<number, LiveLyricSentence[]>;

const statusRank: Record<LiveLyricSentence["translationStatus"], number> = {
  forming: 0,
  pending: 1,
  unavailable: 2,
  ok: 3,
};

/** Upsert one sentence and retain the meeting's lyric history per seat.

 * The fixed-height viewport is responsible for scrolling old lines out of
 * sight. Dropping sentence pairs here made a short lyric list cling to the
 * top of the subtitle frame and lost useful context.
 */
export function upsertLiveLyric(
  state: LiveLyricMap,
  incoming: LiveLyricSentence,
): LiveLyricMap {
  const current = state[incoming.seatId] ?? [];
  const existing = current.find((item) => item.sentenceId === incoming.sentenceId);
  if (existing && incoming.revision < existing.revision) return state;

  let merged = incoming;
  if (existing) {
    // A completed English Zipformer sentence may be replaced once by its
    // SenseVoice correction. Once that correction has locked the source, all
    // later events are translation-only as far as the visible original is
    // concerned — even if a delayed recognizer event has a higher revision.
    const mayReplaceSource = !existing.sourceLocked
      || (existing.recognitionStatus === "correcting" && incoming.sourceLocked === true);
    const keepExistingTranslation =
      (!mayReplaceSource || incoming.sourceText === existing.sourceText)
      && statusRank[existing.translationStatus] > statusRank[incoming.translationStatus];
    merged = {
      ...existing,
      ...incoming,
      sourceText: mayReplaceSource ? incoming.sourceText : existing.sourceText,
      sourceLang: mayReplaceSource ? incoming.sourceLang : existing.sourceLang,
      targetLang: mayReplaceSource ? incoming.targetLang : existing.targetLang,
      sourceLocked: existing.sourceLocked || incoming.sourceLocked,
      recognitionStatus: mayReplaceSource
        ? incoming.recognitionStatus
        : existing.recognitionStatus,
      translatedText: keepExistingTranslation
        ? existing.translatedText
        : incoming.translatedText,
      translationStatus: keepExistingTranslation
        ? existing.translationStatus
        : incoming.translationStatus,
      translationError: keepExistingTranslation
        ? existing.translationError
        : incoming.translationError,
    };
  }

  const nextSeat = current
    .filter((item) => item.sentenceId !== incoming.sentenceId)
    .concat(merged)
    .sort((a, b) => a.sentenceSequence - b.sentenceSequence);
  return { ...state, [incoming.seatId]: nextSeat };
}

export function removeLyricsForUtterance(
  state: LiveLyricMap,
  utteranceId: string,
): LiveLyricMap {
  let changed = false;
  const next: LiveLyricMap = {};
  for (const [seat, sentences] of Object.entries(state)) {
    const filtered = sentences.filter((item) => item.utteranceId !== utteranceId);
    if (filtered.length !== sentences.length) changed = true;
    if (filtered.length) next[Number(seat)] = filtered;
  }
  return changed ? next : state;
}
