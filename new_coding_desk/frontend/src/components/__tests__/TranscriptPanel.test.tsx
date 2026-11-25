import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { TranscriptPanel } from "../TranscriptPanel";
import type { TranslationRecord } from "../../api/types";

describe("TranscriptPanel - realtime translation", () => {
  it("shows translated text inside the two-line live caption", () => {
    render(
      <TranscriptPanel
        entries={[]}
        seatNameMap={{ 1: "张伟" }}
        liveEnabled
        interims={[{
          utteranceId: "utt_live_translated",
          seatId: 1,
          revision: 4,
          sourceLang: "zh",
          targetLang: "en",
          sourceText: "大家好",
          translatedText: "Hello everyone.",
          translationRevision: 3,
          caption: {
            previousLine: "",
            currentLine: "大家好",
            mode: "two_line",
          },
        }]}
      />,
    );

    expect(screen.getByTestId("live-caption-translation")).toHaveTextContent("Hello everyone.");
    expect(screen.getByTestId("live-caption-translation")).toHaveAttribute("data-window-lines", "2");
  });
});

describe("TranscriptPanel - sentence-paired lyrics", () => {
  const first = {
    utteranceId: "utt_lyrics",
    sentenceId: "utt_lyrics:s1",
    sentenceSequence: 1,
    seatId: 1,
    revision: 2,
    sourceLang: "zh",
    targetLang: "en",
    sourceText: "第一句。",
    translatedText: "First sentence.",
    translationStatus: "ok" as const,
  };
  const second = {
    ...first,
    sentenceId: "utt_lyrics:s2",
    sentenceSequence: 2,
    revision: 4,
    sourceText: "第二句。",
    translatedText: "",
    translationStatus: "pending" as const,
  };

  it("renders two sentence pairs with each translation bound to its source", () => {
    render(
      <TranscriptPanel
        entries={[]}
        lyrics={[first, second]}
        interims={[]}
        seatNameMap={{ 1: "张伟" }}
        liveEnabled
      />,
    );
    const pairs = screen.getAllByTestId("live-lyric-pair");
    expect(pairs).toHaveLength(2);
    expect(pairs[0]).toHaveTextContent("第一句。");
    expect(pairs[0]).toHaveTextContent("First sentence.");
    expect(pairs[1]).toHaveTextContent("第二句。");
    expect(pairs[1]).toHaveTextContent("正在翻译");
  });

  it("keeps all sentence pairs and orders them by sentence sequence", () => {
    const third = {
      ...second,
      sentenceId: "utt_lyrics:s3",
      sentenceSequence: 3,
      sourceText: "第三句。",
    };
    render(
      <TranscriptPanel
        entries={[]}
        lyrics={[third, first, second]}
        interims={[]}
        seatNameMap={{ 1: "张伟" }}
        liveEnabled
      />,
    );
    const pairs = screen.getAllByTestId("live-lyric-pair");
    expect(pairs.map((pair) => pair.getAttribute("data-sentence-id"))).toEqual([
      first.sentenceId,
      second.sentenceId,
      third.sentenceId,
    ]);
  });

  it("keeps a fallback caption for a different utterance and only renders overlapping lyrics once", () => {
    render(
      <TranscriptPanel
        entries={[]}
        seatNameMap={{ 1: "张伟", 2: "Alice Wang" }}
        liveEnabled
        lyrics={[first]}
        interims={[{
          utteranceId: first.utteranceId,
          seatId: 1,
          revision: 2,
          sourceLang: "zh",
          targetLang: "en",
          sourceText: first.sourceText,
          translatedText: first.translatedText,
          caption: { previousLine: "", currentLine: first.sourceText, mode: "two_line" },
        }, {
          utteranceId: "utt_carry",
          seatId: 1,
          revision: 0,
          sourceLang: "zh",
          targetLang: "en",
          sourceText: first.sourceText,
          translatedText: first.translatedText,
          caption: { previousLine: "", currentLine: first.sourceText, mode: "two_line" },
        }, {
          utteranceId: "utt_fallback",
          seatId: 2,
          revision: 1,
          sourceLang: "en",
          targetLang: "zh",
          sourceText: "Second speaker.",
          translatedText: "第二位发言人。",
          caption: { previousLine: "", currentLine: "Second speaker.", mode: "two_line" },
        }]}
      />,
    );

    expect(screen.getByTestId("live-lyric-source")).toHaveTextContent(first.sourceText);
    expect(screen.getByTestId("live-caption")).toHaveTextContent("Second speaker.");
    expect(screen.getByTestId("live-caption-translation")).toHaveTextContent("第二位发言人。");
  });

  it("keeps older lyrics visible and shows the authoritative final", () => {
    render(
      <TranscriptPanel
        entries={[]}
        liveFinal={{
          id: 7, meeting_id: 1, seat_id: 1, utterance_id: "utt_lyrics",
          source_lang: "zh", target_lang: "en", source_text: "终稿。",
          translated_text: "Final.", created_at: "2026-01-01T00:00:00Z",
        }}
        lyrics={[first]}
        interims={[]}
        seatNameMap={{ 1: "张伟" }}
        liveEnabled
      />,
    );
    expect(screen.getByTestId("live-lyrics")).toBeInTheDocument();
    expect(screen.getByTestId("live-lyric-translation")).toHaveTextContent("First sentence.");
    expect(screen.getByTestId("live-final-translation")).toHaveTextContent("Final.");
  });

  it("shows an explicit unavailable message for the matching sentence", () => {
    render(
      <TranscriptPanel
        entries={[]}
        lyrics={[{ ...second, translationStatus: "unavailable" }]}
        seatNameMap={{ 1: "张伟" }}
        liveEnabled
      />,
    );
    expect(screen.getByTestId("live-lyric-unavailable")).toHaveTextContent("译文不可用");
  });

  it("keeps complete source and translation text for width-aware browser wrapping", () => {
    const source = "同时，在苗寨举办的全国春晚示范展示活动，通过五G网络上云推介当地的乡村村落，民风风情，以丰富旅游资源吸引超过千万人次观看。";
    const translation = "At the same time, a national Spring Festival Gala demonstration was held in the Miao village to promote local villages and folk customs through the 5G network, attracting more than 10 million views with rich tourism resources.";
    render(
      <TranscriptPanel
        entries={[]}
        lyrics={[{ ...first, sourceText: source, translatedText: translation }]}
        seatNameMap={{ 1: "张伟" }}
        liveEnabled
      />,
    );
    const sourceNode = screen.getByTestId("live-lyric-source");
    const translationNode = screen.getByTestId("live-lyric-translation");
    expect(sourceNode).toHaveTextContent(source);
    expect(translationNode).toHaveTextContent(translation);
    expect(sourceNode.querySelectorAll("span")).toHaveLength(0);
    expect(translationNode.querySelectorAll("span")).toHaveLength(0);
    expect(translationNode).toHaveStyle({
      overflowWrap: "normal",
      wordBreak: "normal",
      hyphens: "none",
    });
    expect(screen.getByTestId("live-lyrics")).toHaveClass("h-[13rem]");
    expect(screen.getByTestId("live-lyric-pairs")).toHaveClass("overflow-y-auto");
  });

  it("keeps the fixed-height lyric viewport pinned to the newest content", () => {
    const { rerender } = render(
      <TranscriptPanel
        entries={[]}
        lyrics={[first]}
        seatNameMap={{ 1: "张伟" }}
        liveEnabled
      />,
    );
    const viewport = screen.getByTestId("live-lyric-pairs");
    Object.defineProperty(viewport, "scrollHeight", {
      configurable: true,
      value: 480,
    });
    viewport.scrollTop = 0;

    rerender(
      <TranscriptPanel
        entries={[]}
        lyrics={[first, second]}
        seatNameMap={{ 1: "张伟" }}
        liveEnabled
      />,
    );

    expect(viewport.scrollTop).toBe(480);
  });

  it("preserves the reader's scroll position until they return to the latest lyrics", () => {
    const panel = (lyrics: (typeof first | typeof second)[]) => (
      <TranscriptPanel entries={[]} lyrics={lyrics} seatNameMap={{ 1: "张伟" }} liveEnabled />
    );
    const { rerender } = render(panel([first, second]));
    const viewport = screen.getByTestId("live-lyric-pairs");
    let scrollHeight = 480;
    Object.defineProperties(viewport, {
      clientHeight: { configurable: true, value: 160 },
      scrollHeight: { configurable: true, get: () => scrollHeight },
    });
    viewport.scrollTop = 85;
    fireEvent.scroll(viewport);

    scrollHeight = 600;
    rerender(panel([first, second, { ...second, sentenceSequence: 3, sentenceId: "utt_lyrics:s3" }]));
    expect(viewport.scrollTop).toBe(85);

    viewport.scrollTop = 440;
    fireEvent.scroll(viewport);
    scrollHeight = 720;
    rerender(panel([first, second, { ...first, sentenceSequence: 3, sentenceId: "utt_lyrics:s3" }]));
    expect(viewport.scrollTop).toBe(560);
  });
});

// ── Sort Order Tests ──────────────────────────────────────────────────────────

describe("TranscriptPanel - sort order (Task 7)", () => {
  const seatNameMap: Record<number, string> = { 1: "Alice Wang", 2: "Bob Li" };

  it("groups UTC timestamps with and without offsets in chronological order", () => {
    vi.stubEnv("TZ", "Asia/Shanghai");
    try {
      const entries: TranslationRecord[] = [{
        id: 3, meeting_id: 1, seat_id: 1, source_lang: "en", target_lang: "zh",
        source_text: "Second sentence.", translated_text: "第二句。",
        created_at: "2026-01-01T18:00:30+08:00", utterance_id: "utt_2",
      }, {
        id: 2, meeting_id: 1, seat_id: 1, source_lang: "en", target_lang: "zh",
        source_text: "First sentence.", translated_text: "第一句。",
        created_at: "2026-01-01T10:00:10", utterance_id: "utt_1",
      }, {
        id: 1, meeting_id: 1, seat_id: 1, source_lang: "en", target_lang: "zh",
        source_text: "Stale revision.", translated_text: "过期版本。",
        created_at: "2026-01-01T10:00:00Z", utterance_id: "utt_1",
      }];

      render(<TranscriptPanel entries={entries} seatNameMap={seatNameMap} />);

      expect(screen.getByTestId("transcript-source")).toHaveTextContent("First sentence. Second sentence.");
      expect(screen.getByTestId("transcript-target")).toHaveTextContent("第一句。第二句。");
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("keeps the previous final in history when the next utterance goes live", () => {
    const previous: TranslationRecord = {
      id: 1, meeting_id: 1, seat_id: 1, source_lang: "en", target_lang: "zh",
      source_text: "Previous sentence.", translated_text: "上一句。",
      created_at: "2026-01-01T10:00:00Z", utterance_id: "utt_1",
    };
    const { rerender } = render(
      <TranscriptPanel entries={[previous]} liveFinal={previous} seatNameMap={seatNameMap} liveEnabled />,
    );
    expect(screen.getByTestId("live-final-translation")).toHaveTextContent("上一句。");
    expect(screen.queryByTestId("transcript-source")).toBeNull();

    rerender(
      <TranscriptPanel
        entries={[previous]}
        liveFinal={previous}
        seatNameMap={seatNameMap}
        liveEnabled
        interims={[{
          utteranceId: "utt_2", seatId: 1, revision: 1, sourceLang: "en", targetLang: "zh",
          sourceText: "Next sentence.", translatedText: "下一句。",
          caption: { previousLine: "", currentLine: "Next sentence.", mode: "two_line" },
        }]}
      />,
    );
    expect(screen.getByTestId("live-caption-translation")).toHaveTextContent("下一句。");
    expect(screen.getByTestId("transcript-source")).toHaveTextContent("Previous sentence.");
    expect(screen.getByTestId("transcript-target")).toHaveTextContent("上一句。");
  });

  it("renders newest-first backend data as oldest-first in UI", () => {
    // Backend returns newest first
    const entries: TranslationRecord[] = [
      {
        id: 3, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "第三句", translated_text: "Third sentence",
        created_at: "2026-01-01T10:03:00Z", utterance_id: "utt_3",
      },
      {
        id: 2, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "第二句", translated_text: "Second sentence",
        created_at: "2026-01-01T10:02:00Z", utterance_id: "utt_2",
      },
      {
        id: 1, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "第一句", translated_text: "First sentence",
        created_at: "2026-01-01T10:01:00Z", utterance_id: "utt_1",
      },
    ];

    render(
      <TranscriptPanel entries={entries} seatNameMap={seatNameMap} />,
    );

    const rows = screen.getAllByTestId("transcript-final");
    expect(rows).toHaveLength(3);

    // Order should be: first, second, third (oldest first)
    const times = rows.map((r) => r.getAttribute("data-created-at"));
    expect(times[0]).toBe("2026-01-01T10:01:00Z");
    expect(times[1]).toBe("2026-01-01T10:02:00Z");
    expect(times[2]).toBe("2026-01-01T10:03:00Z");

    // Text order should also match
    const texts = rows.map((r) => r.textContent);
    expect(texts[0]).toContain("第一句");
    expect(texts[1]).toContain("第二句");
    expect(texts[2]).toContain("第三句");
  });

  it("renders randomly-ordered data as oldest-first in UI", () => {
    const entries: TranslationRecord[] = [
      {
        id: 5, meeting_id: 1, seat_id: 2, source_lang: "en", target_lang: "zh",
        source_text: "Middle", translated_text: "中间",
        created_at: "2026-01-01T10:02:00Z", utterance_id: "utt_5",
      },
      {
        id: 6, meeting_id: 1, seat_id: 2, source_lang: "en", target_lang: "zh",
        source_text: "Latest", translated_text: "最新",
        created_at: "2026-01-01T10:03:00Z", utterance_id: "utt_6",
      },
      {
        id: 4, meeting_id: 1, seat_id: 2, source_lang: "en", target_lang: "zh",
        source_text: "Earliest", translated_text: "最早",
        created_at: "2026-01-01T10:01:00Z", utterance_id: "utt_4",
      },
    ];

    render(
      <TranscriptPanel entries={entries} seatNameMap={seatNameMap} />,
    );

    const rows = screen.getAllByTestId("transcript-final");
    expect(rows).toHaveLength(3);

    const times = rows.map((r) => r.getAttribute("data-created-at"));
    expect(times[0]).toBe("2026-01-01T10:01:00Z");
    expect(times[1]).toBe("2026-01-01T10:02:00Z");
    expect(times[2]).toBe("2026-01-01T10:03:00Z");
  });

  it("uses id as tiebreaker when created_at is identical", () => {
    const entries: TranslationRecord[] = [
      {
        id: 10, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "第十条", translated_text: "Tenth",
        created_at: "2026-01-01T10:05:00Z", utterance_id: "utt_10",
      },
      {
        id: 9, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "第九条", translated_text: "Ninth",
        created_at: "2026-01-01T10:05:00Z", utterance_id: "utt_9",
      },
      {
        id: 11, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "第十一条", translated_text: "Eleventh",
        created_at: "2026-01-01T10:05:00Z", utterance_id: "utt_11",
      },
    ];

    render(
      <TranscriptPanel entries={entries} seatNameMap={seatNameMap} />,
    );

    const rows = screen.getAllByTestId("transcript-final");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("第九条第十条第十一条");
    expect(rows[0]).toHaveAttribute("data-translation-ids", "9,10,11");
  });

  it("interim display is not broken by sort logic", () => {
    const entries: TranslationRecord[] = [
      {
        id: 1, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "过去", translated_text: "Past",
        created_at: "2026-01-01T10:01:00Z", utterance_id: "utt_past",
      },
    ];

    render(
      <TranscriptPanel
        entries={entries}
        interims={[
          { utteranceId: "utt_live", seatId: 1, revision: 1, sourceLang: "zh", targetLang: "en", sourceText: "实时", translatedText: "Live" },
        ]}
        seatNameMap={seatNameMap}
      />,
    );

    // Interim should still render
    expect(screen.getByText("实时")).toBeInTheDocument();
    // Final should also render
    expect(screen.getByText("过去")).toBeInTheDocument();
  });

  it("final arrival removes matching interim, sorts correctly", () => {
    const entries: TranslationRecord[] = [
      {
        id: 20, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "新最终", translated_text: "New final",
        created_at: "2026-01-01T10:06:00Z", utterance_id: "utt_match",
      },
    ];

    render(
      <TranscriptPanel
        entries={entries}
        interims={[
          { utteranceId: "utt_match", seatId: 1, revision: 5, sourceLang: "zh", targetLang: "en", sourceText: "旧中间", translatedText: "" },
          { utteranceId: "utt_other", seatId: 1, revision: 1, sourceLang: "zh", targetLang: "en", sourceText: "其他中间", translatedText: "" },
        ]}
        seatNameMap={seatNameMap}
      />,
    );

    // The interim with utterance_id that matches a final should be removed
    expect(screen.queryByText("旧中间")).not.toBeInTheDocument();
    // Other interim should still show
    expect(screen.getByText("其他中间")).toBeInTheDocument();
    // Final should show
    expect(screen.getByText("New final")).toBeInTheDocument();
  });
});

describe("TranscriptPanel - deduplication preserves sort", () => {
  it("deduplicates same id without duplicating in sorted output", () => {
    const entries: TranslationRecord[] = [
      {
        id: 1, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "唯一", translated_text: "Only",
        created_at: "2026-01-01T10:01:00Z", utterance_id: "utt_1",
      },
      {
        id: 1, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "唯一", translated_text: "Only",
        created_at: "2026-01-01T10:01:00Z", utterance_id: "utt_1",
      },
    ];

    render(
      <TranscriptPanel entries={entries} seatNameMap={{ 1: "Alice" }} />,
    );

    const rows = screen.getAllByTestId("transcript-final");
    expect(rows).toHaveLength(1);
  });
});

describe("TranscriptPanel - bilingual paragraph grouping", () => {
  it("does not merge across speakers or a gap greater than 30 seconds", () => {
    const entries: TranslationRecord[] = [
      { id: 1, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", source_text: "甲", translated_text: "A", created_at: "2026-01-01T10:00:00Z" },
      { id: 2, meeting_id: 1, seat_id: 2, source_lang: "zh", target_lang: "en", source_text: "乙", translated_text: "B", created_at: "2026-01-01T10:00:10Z" },
      { id: 3, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", source_text: "丙", translated_text: "C", created_at: "2026-01-01T10:00:31Z" },
    ];

    render(<TranscriptPanel entries={entries} seatNameMap={{ 1: "主持人", 2: "参会者" }} />);
    expect(screen.getAllByTestId("transcript-final")).toHaveLength(3);
  });

  it("shows a clear unavailable message instead of placeholder translation", () => {
    const entries: TranslationRecord[] = [
      { id: 1, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", source_text: "测试", translated_text: "[translation not available]", created_at: "2026-01-01T10:00:00Z" },
    ];

    render(<TranscriptPanel entries={entries} seatNameMap={{ 1: "主持人" }} />);
    expect(screen.getByText("翻译模型不可用")).toBeInTheDocument();
    expect(screen.queryByText("[translation not available]")).not.toBeInTheDocument();
  });

  it("shows the actual Chinese-to-English direction", () => {
    render(<TranscriptPanel entries={[{
      id: 21, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en",
      source_text: "你好。", translated_text: "Hello.", created_at: "2026-01-01T00:00:00Z",
    }]} seatNameMap={{ 1: "主持人" }} />);
    expect(screen.getByText("ZH → EN")).toBeInTheDocument();
  });

  it("shows the actual English-to-Chinese direction", () => {
    render(<TranscriptPanel entries={[{
      id: 22, meeting_id: 1, seat_id: 1, source_lang: "en", target_lang: "zh",
      source_text: "Welcome.", translated_text: "欢迎。", created_at: "2026-01-01T00:00:00Z",
    }]} seatNameMap={{ 1: "主持人" }} />);
    expect(screen.getByText("EN → ZH")).toBeInTheDocument();
  });
});

describe("TranscriptPanel - stable live speech area", () => {
  it("keeps the latest sentence-final translation in the live subtitle box", () => {
    render(
      <TranscriptPanel
        entries={[]}
        liveFinal={{
          id: 101,
          meeting_id: 1,
          seat_id: 1,
          utterance_id: "utt_live_final",
          source_lang: "zh",
          target_lang: "en",
          source_text: "清华大学的本科。",
          translated_text: "Qinghua University undergraduate.",
          created_at: "2026-01-01T10:00:00Z",
        }}
        interims={[]}
        seatNameMap={{ 1: "主持人" }}
        liveEnabled
      />,
    );

    expect(screen.getByTestId("live-final-translation")).toBeInTheDocument();
    expect(screen.getByTestId("live-final-source")).toHaveTextContent("清华大学的本科。");
    expect(screen.getByTestId("live-final-target")).toHaveTextContent(
      "Qinghua University undergraduate.",
    );
    expect(screen.queryByTestId("live-caption-placeholder")).not.toBeInTheDocument();
  });

  it("keeps a placeholder mounted during an active meeting without speech", () => {
    render(
      <TranscriptPanel
        entries={[]}
        interims={[]}
        seatNameMap={{ 1: "主持人" }}
        liveEnabled
      />,
    );

    expect(screen.getByTestId("live-caption-placeholder")).toBeInTheDocument();
    expect(screen.getByText(/Listening for speech/)).toBeInTheDocument();
  });

  it("keeps the live box mounted while the meeting connection recovers", () => {
    render(
      <TranscriptPanel
        entries={[]}
        interims={[]}
        seatNameMap={{ 1: "主持人" }}
        liveEnabled
        liveReconnecting
      />,
    );

    expect(screen.getByTestId("live-caption-placeholder")).toBeInTheDocument();
    expect(screen.getByText(/Reconnecting live speech/)).toBeInTheDocument();
  });

  it("keeps an empty caption in the fixed live box", () => {
    render(
      <TranscriptPanel
        entries={[]}
        interims={[{
          utteranceId: "utt_live",
          seatId: 1,
          revision: 1,
          sourceLang: "zh",
          targetLang: "en",
          sourceText: "",
          translatedText: "",
          caption: { previousLine: "", currentLine: "", mode: "live" },
        }]}
        seatNameMap={{ 1: "主持人" }}
        liveEnabled
      />,
    );

    expect(screen.getByTestId("transcript-interim")).toBeInTheDocument();
    expect(screen.getByTestId("transcript-interim")).toHaveClass("min-h-[7.25rem]");
  });
});

describe("TranscriptPanel - background finalization", () => {
  it("moves rolled text to pending history while keeping the live box mounted", () => {
    render(
      <TranscriptPanel
        entries={[]}
        interims={[]}
        pendingFinals={[{
          utteranceId: "utt_pending",
          seatId: 1,
          sourceLang: "zh",
          targetLang: "en",
          sourceText: "已完成的实时识别文本。",
          boundaryReason: "max_duration",
        }]}
        seatNameMap={{ 1: "主持人" }}
        liveEnabled
      />,
    );

    expect(screen.getByTestId("live-caption-placeholder")).toBeInTheDocument();
    expect(screen.getByTestId("transcript-pending-final")).toHaveTextContent(
      "已完成的实时识别文本。",
    );
    expect(screen.getByText(/Translating/)).toBeInTheDocument();
  });

  it("hides a pending item once the matching final is available", () => {
    const final: TranslationRecord = {
      id: 99,
      meeting_id: 1,
      seat_id: 1,
      utterance_id: "utt_same",
      source_lang: "zh",
      target_lang: "en",
      source_text: "最终中文。",
      translated_text: "Final English.",
      created_at: "2026-01-01T10:00:00Z",
    };
    render(
      <TranscriptPanel
        entries={[final]}
        pendingFinals={[{
          utteranceId: "utt_same",
          seatId: 1,
          sourceLang: "zh",
          targetLang: "en",
          sourceText: "待处理中文。",
          boundaryReason: "soft_sentence_limit",
        }]}
        seatNameMap={{ 1: "主持人" }}
      />,
    );

    expect(screen.queryByTestId("transcript-pending-final")).not.toBeInTheDocument();
    expect(screen.getByText("Final English.")).toBeInTheDocument();
  });
});
