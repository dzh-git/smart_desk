import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TranscriptPanel } from "../TranscriptPanel";
import type { TranslationRecord } from "../../api/types";

// ── Sort Order Tests ──────────────────────────────────────────────────────────

describe("TranscriptPanel - sort order (Task 7)", () => {
  const seatNameMap: Record<number, string> = { 1: "Alice Wang", 2: "Bob Li" };

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
});

describe("TranscriptPanel - stable live speech area", () => {
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
