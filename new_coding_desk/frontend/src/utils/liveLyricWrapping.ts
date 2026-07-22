const SENTENCE_END = /[.!?。！？][\]})"'”’]*$/u;
const CLAUSE_END = /[,;:.!?，；：。！？][\]})"'”’]*$/u;
const HAS_WORD = /[\p{L}\p{N}]/u;

export const ENGLISH_SENTENCE_WRAP_WORDS = 30;
export const ENGLISH_CLAUSE_WRAP_WORDS = 40;
export const ENGLISH_FORCE_WRAP_WORDS = 50;

/**
 * Split a live lyric into explicit display lines without changing its text.
 *
 * English waits for a strong sentence boundary after 30 words, accepts any
 * clause punctuation after 40, and caps a line at 50 words. Chinese and
 * unknown-language text continue to use width-aware browser wrapping.
 */
export function splitLiveLyricDisplayLines(
  text: string,
  language: string,
): string[] {
  const clean = text.trim().replace(/\s+/gu, " ");
  if (!clean || language.toLowerCase() !== "en") return clean ? [clean] : [];

  const tokens = clean.split(" ");
  const lines: string[] = [];
  let current: string[] = [];
  let wordCount = 0;

  const commit = () => {
    if (!current.length) return;
    lines.push(current.join(" "));
    current = [];
    wordCount = 0;
  };

  for (const token of tokens) {
    current.push(token);
    if (HAS_WORD.test(token)) wordCount += 1;

    const afterSentenceThreshold =
      wordCount > ENGLISH_SENTENCE_WRAP_WORDS && SENTENCE_END.test(token);
    const afterClauseThreshold =
      wordCount > ENGLISH_CLAUSE_WRAP_WORDS && CLAUSE_END.test(token);
    const reachedHardLimit = wordCount >= ENGLISH_FORCE_WRAP_WORDS;

    if (afterSentenceThreshold || afterClauseThreshold || reachedHardLimit) {
      commit();
    }
  }
  commit();
  return lines;
}
