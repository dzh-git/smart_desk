import { describe, expect, it } from "vitest";
import { splitLiveLyricDisplayLines } from "./liveLyricWrapping";

function words(count: number, start = 1): string[] {
  return Array.from({ length: count }, (_, index) => `word${start + index}`);
}

describe("splitLiveLyricDisplayLines", () => {
  it("waits for the next sentence-ending punctuation after 30 words", () => {
    const input = [...words(31), "word32.", ...words(4, 33)].join(" ");
    const lines = splitLiveLyricDisplayLines(input, "en");

    expect(lines).toHaveLength(2);
    expect(lines[0].split(" ")).toHaveLength(32);
    expect(lines[0]).toMatch(/word32\.$/);
    expect(lines[1]).toBe("word33 word34 word35 word36");
  });

  it("accepts clause punctuation after 40 words when no period arrives", () => {
    const input = [...words(41), "word42,", ...words(3, 43)].join(" ");
    const lines = splitLiveLyricDisplayLines(input, "en");

    expect(lines).toHaveLength(2);
    expect(lines[0].split(" ")).toHaveLength(42);
    expect(lines[0]).toMatch(/word42,$/);
  });

  it("forces a line break at 50 words without splitting a word", () => {
    const input = words(53).join(" ");
    const lines = splitLiveLyricDisplayLines(input, "en");

    expect(lines[0].split(" ")).toHaveLength(50);
    expect(lines[0]).toMatch(/word50$/);
    expect(lines[1]).toBe("word51 word52 word53");
  });

  it("does not apply word-count segmentation to Chinese text", () => {
    const input = "中文内容继续由浏览器根据文本框宽度自然换行。";
    expect(splitLiveLyricDisplayLines(input, "zh")).toEqual([input]);
  });

  it("splits the reported course-assessment sample at the next period", () => {
    const input = "Could you tell us more about the assessment of the course, Certainly, in addition to your participation in us, which accounts for 10%, there will be a midter test, 20%, a final exam, 30% and a research paper, 40%. Any questions, Do we have any reading assignments. Yes, I believe you've all got your textbook";
    const lines = splitLiveLyricDisplayLines(input, "en");

    expect(lines).toHaveLength(2);
    expect(lines[0]).toMatch(/research paper, 40%\.$/);
    expect(lines[1]).toMatch(/^Any questions,/);
  });
});
