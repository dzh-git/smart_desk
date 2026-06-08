/**
 * SmartDesk Speech E2E — Deterministic Two-Line Caption Display Test.
 *
 * Phase 05 / Task 117 — three-defect fix iteration.
 *
 * Flow (same utterance_id across ALL steps):
 *   1. Create meeting, set speaker seat.
 *   2. Set up browser WS monkey-patch (addInitScript).
 *   3. Navigate admin page (browser WS is now mocked).
 *   4. Connect REAL broadcast WS + REAL speech WS from Node.js.
 *   5. Send 'start' on speech WS → get realUid.
 *   6. Send deterministic translation_interim (utterance_id = realUid) via mock WS.
 *   7. Verify DOM live caption shows deterministic content.
 *   8. Send same-text rev2 + different-text rev3 via mock WS.
 *   9. Verify revision replacement.
 *  10. Send PCM frames + end_hint on real speech WS.
 *  11. Wait for translation_final on real broadcast WS (utterance_id === realUid).
 *  12. Send translation_final via mock WS (utterance_id = realUid, source_text = real final).
 *  13. Verify live-caption cleared.
 *  14. Wait for doFetch → query [data-testid="transcript-final"][data-utterance-id="${realUid}"].
 *  15. Verify DOM source_text matches WS final source_text.
 *  16. Verify DB source_text matches DOM and WS.
 *  17. Compute report.pass from individual booleans, not hardcoded.
 */

import { test, expect } from "@playwright/test";
/* eslint-disable @typescript-eslint/no-explicit-any */
import WebSocket from "ws";
import * as path from "path";
import * as fs from "fs";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ---- Constants -------------------------------------------------------------

const BACKEND = "http://localhost:8000";
const FRAME_SIZE = 3200; // 100ms @ 16kHz s16le mono
const PCM_FIXTURE = path.resolve(
  __dirname, "..", "..", "tests", "fixtures", "speech_sample.pcm",
);

const PREV_LINE = "中华民族遭受了前所未有的劫难，";
const INITIAL_CURR_LINE = "一批又一批仁人志士为救国救民而苦苦追寻。";
const UPDATED_CURR_LINE = "随后他们继续探索新的道路。";
const DETERMINISTIC_SOURCE_TEXT = PREV_LINE + INITIAL_CURR_LINE;

// ---- Types -----------------------------------------------------------------

interface DeterministicCaptionReport {
  utterance_id: string;
  // Caption content
  previous_line: string;
  current_line_initial: string;
  current_line_updated: string;
  dom_previous_line: string;
  dom_current_line_initial: string;
  dom_current_line_updated: string;
  max_live_caption_line_count: number;
  dom_caption_matches_payload: boolean;
  // Revision behaviour
  revision_update_replaced_current_line: boolean;
  no_accumulation_on_same_text: boolean;
  // Final behaviour
  final_cleared_live_caption: boolean;
  final_dom_text_shown: boolean;
  final_dom_text: string;
  final_ws_text: string;
  final_db_text: string;
  final_dom_matches_ws: boolean;
  final_dom_matches_db: boolean;
  final_db_matches_ws: boolean;
  // Overall
  pass: boolean;
  reason: string;
}

// ---- Helpers ---------------------------------------------------------------

function loadPcmFrames(count = 20): Buffer[] {
  if (!fs.existsSync(PCM_FIXTURE)) throw new Error(`PCM fixture not found at ${PCM_FIXTURE}.`);
  const raw = fs.readFileSync(PCM_FIXTURE);
  const frames: Buffer[] = [];
  for (let i = 0; i < count; i++) {
    const start = i * FRAME_SIZE;
    if (start + FRAME_SIZE > raw.length) break;
    frames.push(raw.subarray(start, start + FRAME_SIZE));
  }
  return frames;
}

async function wsConnect(url: string, timeoutMs = 8000): Promise<WebSocket> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    const timer = setTimeout(() => { ws.close(); reject(new Error(`WS connect timeout (${url})`)); }, timeoutMs);
    ws.on("open", () => { clearTimeout(timer); resolve(ws); });
    ws.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

function wsSendJson(ws: WebSocket, data: unknown): void { ws.send(JSON.stringify(data)); }

async function wsReceiveJson(ws: WebSocket, timeoutMs = 15000): Promise<any> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => { clearTimeout(timer); ws.removeListener("message", handler); ws.removeListener("error", errorHandler); };
    const timer = setTimeout(() => { if (settled) return; settled = true; cleanup(); reject(new Error("WS recv timeout")); }, timeoutMs);
    const handler = (raw: Buffer) => {
      if (settled) return; settled = true; cleanup();
      try { resolve(JSON.parse(raw.toString("utf-8"))); }
      catch { reject(new Error(`WS non-JSON: ${raw.toString("utf-8").slice(0, 100)}`)); }
    };
    const errorHandler = (err: Error) => { if (settled) return; settled = true; cleanup(); reject(err); };
    ws.on("message", handler);
    ws.on("error", errorHandler);
  });
}

async function sendMockWsMessage(page: any, payload: unknown): Promise<void> {
  const json = JSON.stringify(payload);
  await page.evaluate((msg: string) => {
    const senders = (window as any).__mockWsSenders;
    if (senders && senders.length > 0) senders[0](msg);
  }, json);
}

// ---- Test ------------------------------------------------------------------

test.describe("Deterministic two-line live caption", () => {
  let meetingId: number;

  test("same-uuid flow: deterministic caption + real ASR final", async ({ page, request }) => {
    test.setTimeout(120_000);

    // ── 0. Initialise report ────────────────────────────────────────────────
    const rep = (partial: Partial<DeterministicCaptionReport> = {}): DeterministicCaptionReport => ({
      utterance_id: "",
      previous_line: PREV_LINE, current_line_initial: INITIAL_CURR_LINE, current_line_updated: UPDATED_CURR_LINE,
      dom_previous_line: "", dom_current_line_initial: "", dom_current_line_updated: "",
      max_live_caption_line_count: 0, dom_caption_matches_payload: false,
      revision_update_replaced_current_line: false, no_accumulation_on_same_text: false,
      final_cleared_live_caption: false, final_dom_text_shown: false,
      final_dom_text: "", final_ws_text: "", final_db_text: "",
      final_dom_matches_ws: false, final_dom_matches_db: false, final_db_matches_ws: false,
      pass: false, reason: "",
      ...partial,
    });
    const report: DeterministicCaptionReport = rep();

    // ── 1. Create active meeting + speaker seat ──────────────────────────────
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeMeeting = await activeResp.json();
    if (activeMeeting?.data?.id) {
      await request.post(`${BACKEND}/api/meetings/${activeMeeting.data.id}/end`);
    }
    const createResp = await (await request.post(`${BACKEND}/api/meetings`, {
      data: { title: `DetCaption ${Date.now()}`, description: "Same-uuid deterministic test" },
      headers: { "Content-Type": "application/json" },
    })).json();
    meetingId = createResp?.data?.id;
    expect(meetingId).toBeGreaterThan(0);
    await request.post(`${BACKEND}/api/meetings/${meetingId}/start`);
    const speakerResp = await (await request.post(`${BACKEND}/api/seats/speaker`, {
      data: { seat_id: 1 },
      headers: { "Content-Type": "application/json" },
    })).json();
    expect(speakerResp?.data?.seat_id).toBe(1);
    console.log(`[DetCaption] Meeting ${meetingId} ready`);

    // ── 2. Set up browser WS monkey-patch BEFORE navigation ──────────────────
    // The prefix is the URL path prefix that the admin page connects to.
    // The realUid will be captured later from the real speech WS; we use the
    // same path prefix so that the mock intercepts correctly.
    const wsPathPrefix = `/ws/${meetingId}`;
    await page.addInitScript(`
      (() => {
        const OrigWs = window.WebSocket;
        const prefix = "${wsPathPrefix}";
        const senders = [];
        window.__mockWsSenders = senders;

        window.WebSocket = function(url, ...args) {
          const urlStr = String(url);
          // Only intercept /ws/{meeting_id} (broadcast WS), not /ws/speech/...
          if (!urlStr.includes(prefix) || urlStr.includes('/speech/')) {
            return new OrigWs(url, ...args);
          }

          const listeners = {};
          const mock = {
            url: urlStr,
            readyState: 1, CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3,
            onopen: null, onmessage: null, onclose: null, onerror: null,
            send() {},
            close() { mock.readyState = 3; if (mock.onclose) mock.onclose({ code: 1000 }); },
            addEventListener(event, handler) {
              if (event === 'open') setTimeout(() => handler({}), 0);
              if (event === 'message') listeners[event] = handler;
            },
          };

          senders.push(function sendToPage(msg) {
            if (typeof msg === 'string') {
              const event = { data: msg };
              if (mock.onmessage) mock.onmessage(event);
              if (listeners.message) listeners.message(event);
            }
          });

          setTimeout(() => { if (mock.onopen) mock.onopen({}); }, 50);
          return mock;
        };
      })();
    `);

    // ── 3. Navigate admin page ───────────────────────────────────────────────
    await page.goto("/");
    await page.waitForSelector("text=Connected", { timeout: 15_000 });
    await page.waitForTimeout(1000);
    console.log("[DetCaption] Admin page loaded, WS mock active");

    // ── 4. Wait for mock WS sender ───────────────────────────────────────────
    let senderReady = false;
    for (let i = 0; i < 10; i++) {
      const exists = await page.evaluate(() => { const s = (window as any).__mockWsSenders; return !!(s && s.length > 0); });
      if (exists) { senderReady = true; break; }
      await page.waitForTimeout(300);
    }
    expect(senderReady).toBe(true);
    console.log("[DetCaption] Mock WS sender ready");

    // ── 5. Connect REAL broadcast + speech WS, get realUid ───────────────────
    const broadcastWs = await wsConnect(`ws://localhost:8000/ws/${meetingId}?seat=0`);
    await wsReceiveJson(broadcastWs, 5000); // consume "connected"
    const speechWs = await wsConnect(`ws://localhost:8000/ws/speech/${meetingId}?seat=1`);

    wsSendJson(speechWs, { type: "start", sample_rate: 16000, encoding: "pcm_s16le", channels: 1 });
    const startedMsg = await wsReceiveJson(speechWs, 10_000);
    const realUid: string = startedMsg.utterance_id;
    report.utterance_id = realUid;
    expect(realUid).toMatch(/^utt_\d+_\d+_\d{6}$/);
    console.log(`[DetCaption] realUid = ${realUid}`);

    // ── 6. Send deterministic translation_interim (rev 1) VIA MOCK WS ────────
    // All mock messages use realUid so the interimMap key matches the DB record.
    await sendMockWsMessage(page, {
      event: "translation_interim",
      meeting_id: meetingId,
      timestamp: Math.floor(Date.now() / 1000),
      payload: {
        utterance_id: realUid, seat_id: 1, revision: 1,
        source_lang: "zh", target_lang: "en",
        source_text: DETERMINISTIC_SOURCE_TEXT,
        translated_text: "", is_final: false,
        caption: { previous_line: PREV_LINE, current_line: INITIAL_CURR_LINE, mode: "two_line" },
      },
    });
    console.log(`[DetCaption] Mock rev1: prev="${PREV_LINE}" curr="${INITIAL_CURR_LINE}"`);

    // ── 7. Verify DOM live caption (rev 1) ───────────────────────────────────
    await page.waitForSelector('[data-testid="live-caption"]', { timeout: 10_000 });

    report.dom_previous_line = await page.$eval(
      '[data-testid="live-caption-previous"]', (el: any) => (el.textContent || "").trim(),
    );
    report.dom_current_line_initial = await page.$eval(
      '[data-testid="live-caption-current"]', (el: any) => (el.textContent || "").trim(),
    );
    console.log(`[DetCaption] DOM rev1: prev="${report.dom_previous_line}" curr="${report.dom_current_line_initial}"`);

    const domCaptionOk = report.dom_previous_line === PREV_LINE && report.dom_current_line_initial === INITIAL_CURR_LINE;
    report.dom_caption_matches_payload = domCaptionOk;
    expect(report.dom_previous_line).toBe(PREV_LINE);
    expect(report.dom_current_line_initial).toBe(INITIAL_CURR_LINE);

    const lc1 = (report.dom_previous_line.length > 0 ? 1 : 0) + (report.dom_current_line_initial.length > 0 ? 1 : 0);
    report.max_live_caption_line_count = lc1;
    expect(lc1).toBeLessThanOrEqual(2);

    // No source_text-only interims alongside caption
    expect(await page.$$('[data-testid="transcript-interim"]')).toHaveLength(0);

    // ── 8. Send same-text rev2 + different-text rev3 via mock WS ──────────────
    // Rev2: same text — verify no accumulation
    await sendMockWsMessage(page, {
      event: "translation_interim",
      meeting_id: meetingId,
      timestamp: Math.floor(Date.now() / 1000),
      payload: {
        utterance_id: realUid, seat_id: 1, revision: 2,
        source_lang: "zh", target_lang: "en",
        source_text: DETERMINISTIC_SOURCE_TEXT,
        translated_text: "", is_final: false,
        caption: { previous_line: PREV_LINE, current_line: INITIAL_CURR_LINE, mode: "two_line" },
      },
    });
    await page.waitForTimeout(400);
    const domPrev2 = await page.$eval('[data-testid="live-caption-previous"]', (el: any) => (el.textContent || "").trim());
    const domCurr2 = await page.$eval('[data-testid="live-caption-current"]', (el: any) => (el.textContent || "").trim());
    report.no_accumulation_on_same_text = (domPrev2 === PREV_LINE && domCurr2 === INITIAL_CURR_LINE);
    expect(report.no_accumulation_on_same_text).toBe(true);

    // Rev3: COMPLETELY DIFFERENT current_line → proves replacement
    await sendMockWsMessage(page, {
      event: "translation_interim",
      meeting_id: meetingId,
      timestamp: Math.floor(Date.now() / 1000),
      payload: {
        utterance_id: realUid, seat_id: 1, revision: 3,
        source_lang: "zh", target_lang: "en",
        source_text: PREV_LINE + UPDATED_CURR_LINE,
        translated_text: "", is_final: false,
        caption: { previous_line: PREV_LINE, current_line: UPDATED_CURR_LINE, mode: "two_line" },
      },
    });
    await page.waitForTimeout(400);

    report.dom_current_line_updated = await page.$eval(
      '[data-testid="live-caption-current"]', (el: any) => (el.textContent || "").trim(),
    );
    console.log(`[DetCaption] DOM rev3: curr="${report.dom_current_line_updated}"`);

    const replaced = report.dom_current_line_updated === UPDATED_CURR_LINE;
    report.revision_update_replaced_current_line = replaced;
    expect(replaced).toBe(true);
    expect(report.dom_current_line_updated).not.toBe(INITIAL_CURR_LINE);
    expect(report.dom_current_line_updated).not.toContain(PREV_LINE);
    expect(report.dom_current_line_updated).not.toContain(INITIAL_CURR_LINE + UPDATED_CURR_LINE);

    // ── 9. Send PCM frames on real speech WS ─────────────────────────────────
    const frames = loadPcmFrames(15);
    for (let i = 0; i < frames.length; i++) {
      speechWs.send(frames[i]);
      if (i < frames.length - 1) await new Promise((r) => setTimeout(r, 20));
    }
    await new Promise((r) => setTimeout(r, 300));

    // ── 10. Send end_hint on real speech WS ──────────────────────────────────
    wsSendJson(speechWs, { type: "end_hint" });

    // ── 11. Wait for translation_final on REAL broadcast WS ───────────────────
    let realFinalSourceText = "";
    let realTranslationId = 0;
    const finalDeadline = Date.now() + 30_000;
    while (Date.now() < finalDeadline) {
      try {
        const msg = await wsReceiveJson(broadcastWs, 10_000);
        if (msg.event === "translation_final" && msg.payload?.utterance_id === realUid) {
          realFinalSourceText = msg.payload.source_text;
          realTranslationId = msg.payload.translation_id;
          break;
        }
      } catch { break; }
    }
    expect(realFinalSourceText).toBeTruthy();
    report.final_ws_text = realFinalSourceText;
    console.log(`[DetCaption] Real final: uid=${realUid} source="${realFinalSourceText}"`);

    speechWs.close();
    broadcastWs.close();

    // ── 12. Send translation_final VIA MOCK WS (same realUid) ────────────────
    await sendMockWsMessage(page, {
      event: "translation_final",
      meeting_id: meetingId,
      timestamp: Math.floor(Date.now() / 1000),
      payload: {
        utterance_id: realUid,
        translation_id: realTranslationId,
        seat_id: 1,
        source_lang: "zh", target_lang: "en",
        source_text: realFinalSourceText,
        translated_text: "",
        source_type: "offline_rescore",
      },
    });
    console.log("[DetCaption] Mock translation_final sent (same realUid)");

    // ── 13. Verify live caption cleared ──────────────────────────────────────
    await page.waitForTimeout(3000);
    const liveCaptionEl = await page.$('[data-testid="live-caption"]');
    report.final_cleared_live_caption = (liveCaptionEl === null);
    expect(report.final_cleared_live_caption).toBe(true);
    console.log("[DetCaption] Live caption cleared after final ✓");

    // ── 14. Verify final DOM for SAME utterance_id ───────────────────────────
    const finalRowSelector = `[data-testid="transcript-final"][data-utterance-id="${realUid}"]`;
    let finalRow: any = null;
    try {
      finalRow = await page.waitForSelector(finalRowSelector, { timeout: 10_000 });
    } catch {
      console.log(`[DetCaption] Final row NOT found for ${realUid}`);
    }
    report.final_dom_text_shown = (finalRow !== null);

    let domFinalText = "";
    if (finalRow) {
      domFinalText = await page.$eval(
        `${finalRowSelector} [data-testid="transcript-source"]`,
        (el: any) => (el.textContent || "").trim(),
      );
    }
    report.final_dom_text = domFinalText;
    console.log(`[DetCaption] DOM final: uid=${realUid} text="${domFinalText}"`);

    report.final_dom_matches_ws = (domFinalText === realFinalSourceText);
    // Assert final DOM matches WS final payload
    expect(domFinalText).toBe(realFinalSourceText);

    // ── 15. Verify DB record for SAME utterance_id ───────────────────────────
    const transResp = await (await request.get(`${BACKEND}/api/translations?meeting_id=${meetingId}`)).json();
    const entries: any[] = transResp?.data?.entries ?? [];
    const matches = entries.filter((e: any) => e.utterance_id === realUid);
    const dbRecord = matches.length > 0 ? matches[0] : null;
    const dbSourceText = dbRecord?.source_text ?? "";
    report.final_db_text = dbSourceText;

    report.final_dom_matches_db = (domFinalText === dbSourceText && dbRecord !== null);
    report.final_db_matches_ws = (dbSourceText === realFinalSourceText);
    console.log(`[DetCaption] DB: uid=${realUid} text="${dbSourceText}"`);

    // Assert DB matches DOM and WS
    expect(dbRecord).not.toBeNull();
    expect(dbSourceText).toBe(domFinalText);
    expect(dbSourceText).toBe(realFinalSourceText);

    // ── 16. Compute pass from individual booleans ────────────────────────────
    const allPassed =
      report.dom_caption_matches_payload &&
      report.revision_update_replaced_current_line &&
      report.no_accumulation_on_same_text &&
      report.final_cleared_live_caption &&
      report.final_dom_text_shown &&
      report.final_dom_matches_ws &&
      report.final_dom_matches_db &&
      report.final_db_matches_ws;

    report.pass = allPassed;
    report.reason = allPassed
      ? `Same-uuid flow passed: deterministic caption displayed, rev3 replaced current_line, `
        + `final DOM matches WS and DB (uid=${realUid}).`
      : "Some assertions failed — see individual boolean fields.";

    console.log(`[DetCaption] All checks: caption=${report.dom_caption_matches_payload} ` +
      `replace=${report.revision_update_replaced_current_line} ` +
      `noAccum=${report.no_accumulation_on_same_text} ` +
      `cleared=${report.final_cleared_live_caption} ` +
      `domShown=${report.final_dom_text_shown} ` +
      `domWS=${report.final_dom_matches_ws} ` +
      `domDB=${report.final_dom_matches_db} ` +
      `dbWS=${report.final_db_matches_ws} ` +
      `→ pass=${report.pass}`);

    await writeCombinedReport(report);
    console.log("[DetCaption] All assertions passed ✓");
  });
});

// ---- Combined Report Writer ---------------------------------------------------

async function writeCombinedReport(dtc: DeterministicCaptionReport): Promise<void> {
  const reportPath = path.resolve(__dirname, "..", "..", "working", "speech-caption-e2e-report.json");
  const dir = path.dirname(reportPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  let existing: any = {};
  try { existing = JSON.parse(fs.readFileSync(reportPath, "utf-8")); } catch { /* ok */ }

  const combined = {
    real_speech_smoke: existing.real_speech_smoke ?? null,
    deterministic_two_line_caption: dtc,
  };

  fs.writeFileSync(reportPath, JSON.stringify(combined, null, 2) + "\n", "utf-8");
  console.log(`[DetCaption] Combined report written to ${reportPath}`);
}
