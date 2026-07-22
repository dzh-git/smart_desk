import { describe, expect, it } from "vitest";
import {
  removeLyricsForUtterance,
  upsertLiveLyric,
  type LiveLyricMap,
} from "../liveLyrics";
import type { LiveLyricSentence } from "../../types";

function lyric(sequence: number, overrides: Partial<LiveLyricSentence> = {}): LiveLyricSentence {
  return {
    utteranceId: "utt_1",
    sentenceId: `utt_1:s${sequence}`,
    sentenceSequence: sequence,
    seatId: 1,
    revision: sequence,
    sourceLang: "zh",
    targetLang: "en",
    sourceText: `第${sequence}句`,
    translatedText: "",
    translationStatus: "forming",
    ...overrides,
  };
}

describe("live lyric state", () => {
  it("retains lyric history so the fixed viewport can scroll it", () => {
    let state: LiveLyricMap = {};
    state = upsertLiveLyric(state, lyric(1));
    state = upsertLiveLyric(state, lyric(2));
    state = upsertLiveLyric(state, lyric(3));
    expect(state[1].map((item) => item.sentenceSequence)).toEqual([1, 2, 3]);
  });

  it("clears an old translation when a higher revision corrects its source", () => {
    let state = upsertLiveLyric({}, lyric(1));
    state = upsertLiveLyric(state, lyric(1, {
      translationStatus: "ok",
      translatedText: "First sentence.",
    }));
    state = upsertLiveLyric(state, lyric(1, {
      revision: 2,
      sourceText: "第一句。",
      translationStatus: "forming",
    }));
    expect(state[1][0].sourceText).toBe("第一句。");
    expect(state[1][0].translatedText).toBe("");
    expect(state[1][0].translationStatus).toBe("forming");
  });

  it("does not downgrade a completed translation when source text is unchanged", () => {
    let state = upsertLiveLyric({}, lyric(1));
    state = upsertLiveLyric(state, lyric(1, {
      translationStatus: "ok",
      translatedText: "First sentence.",
    }));
    state = upsertLiveLyric(state, lyric(1, {
      revision: 2,
      translationStatus: "forming",
    }));
    expect(state[1][0].translatedText).toBe("First sentence.");
    expect(state[1][0].translationStatus).toBe("ok");
  });

  it("allows one sentence-final correction then freezes its source text", () => {
    let state = upsertLiveLyric({}, lyric(1, {
      sourceLang: "en",
      targetLang: "zh",
      sourceText: "when do you usually do that",
      recognitionStatus: "correcting",
      sourceLocked: false,
      translationStatus: "pending",
    }));
    state = upsertLiveLyric(state, lyric(1, {
      revision: 2,
      sourceLang: "en",
      targetLang: "zh",
      sourceText: "When do you usually do that?",
      recognitionStatus: "ok",
      sourceLocked: true,
      translationStatus: "pending",
    }));
    state = upsertLiveLyric(state, lyric(1, {
      revision: 3,
      sourceText: "When do you usually do that I do it every night.",
      recognitionStatus: "ok",
      sourceLocked: false,
      translationStatus: "forming",
    }));
    expect(state[1][0].sourceText).toBe("When do you usually do that?");
    expect(state[1][0].sourceLocked).toBe(true);
  });

  it("ignores stale revisions and removes only an explicitly cancelled utterance", () => {
    let state = upsertLiveLyric({}, lyric(1, { revision: 5 }));
    state = upsertLiveLyric(state, lyric(1, { revision: 4, sourceText: "旧结果" }));
    expect(state[1][0].sourceText).toBe("第1句");
    expect(removeLyricsForUtterance(state, "other")).toBe(state);
    expect(removeLyricsForUtterance(state, "utt_1")).toEqual({});
  });
});
