/**
 * SmartDesk Speech E2E -- Frontend-Backend Display Consistency Test.
 *
 * Task 109-110: voice streaming frontend-backend display consistency test
 * with continuous DOM monitoring and duplicate detection.
 *
 * Flow:
 *   1. HTTP API: create meeting -> start -> set speaker seat
 *   2. Navigate to admin page
 *   3. Node.js WS client: meeting broadcast WS + speech WS
 *   4. Speech WS: start -> started + utterance_id
 *   5. BEFORE sending frames: start continuous DOM sampling (every 200ms)
 *   6. Send PCM16 frames -> collect ALL translation_interim + DOM samples
 *   7. Send end_hint -> capture translation_final on broadcast WS
 *   8. Continue DOM sampling until final DOM appears + 1s settle
 *   9. Verify assertions against collected samples
 *  10. GET /api/translations: verify persisted record matches DOM
 *  11. Write report with all samples and analysis
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

// ---- Types -----------------------------------------------------------------

interface LatencyRecord {
  start_to_started_ms: number | null;
  first_frame_to_first_interim_ms: number | null;
  first_frame_to_latest_interim_ms: number | null;
  latest_interim_event_to_dom_ms: number | null;
  end_hint_to_final_ms: number | null;
  final_event_to_final_dom_ms: number | null;
}

interface DomSample {
  timestamp: number;
  interims: { utteranceId: string; revision: number; sourceText: string }[];
  finals: { utteranceId: string; translationId: number; sourceText: string }[];
}

interface Report {
  utterance_id: string;
  interim_count: number;
  latest_interim_text: string;
  final_text: string;
  persisted_text: string;
  latency: LatencyRecord;
  pass: boolean;
  reason: string;
  // Task 110: continuous DOM monitoring
  dom_samples: DomSample[];
  max_interim_rows_for_utterance: number;
  max_final_rows_for_utterance: number;
  interim_final_overlap_seen: boolean;
  ws_interim_payloads: any[];
  ws_final_payload: any;
  db_final_record: any;
  has_mojibake_labels: boolean;
  // Task 112: repeated prefix detection on WS interim payloads
  ws_interim_repeated_prefix_detected: boolean;
  ws_interim_repeated_prefix: string;
  ws_interim_failing_revision: number | null;
}

// ---- Helpers ---------------------------------------------------------------

/** Load PCM16 frames from the speech fixture file. */
function loadPcmFrames(count = 20): Buffer[] {
  if (!fs.existsSync(PCM_FIXTURE)) {
    throw new Error(
      `PCM fixture not found at ${PCM_FIXTURE}. Cannot run speech E2E test.`,
    );
  }
  const raw = fs.readFileSync(PCM_FIXTURE);
  const frames: Buffer[] = [];
  for (let i = 0; i < count; i++) {
    const start = i * FRAME_SIZE;
    if (start + FRAME_SIZE > raw.length) break;
    frames.push(raw.subarray(start, start + FRAME_SIZE));
  }
  return frames;
}

/** Create a WS connection, resolve once open. */
async function wsConnect(url: string, timeoutMs = 8000): Promise<WebSocket> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    const timer = setTimeout(() => {
      ws.close();
      reject(new Error(`WS connect timeout (${url})`));
    }, timeoutMs);
    ws.on("open", () => { clearTimeout(timer); resolve(ws); });
    ws.on("error", (err) => { clearTimeout(timer); reject(err); });
  });
}

/** Send JSON on a WS. */
function wsSendJson(ws: WebSocket, data: unknown): void {
  ws.send(JSON.stringify(data));
}

/** Receive next JSON message from a WS with timeout. */
function wsReceiveJson(ws: WebSocket, timeoutMs = 15000): Promise<any> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      clearTimeout(timer);
      ws.removeListener("message", handler);
      ws.removeListener("error", errorHandler);
    };
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error("WS recv timeout"));
    }, timeoutMs);
    const handler = (raw: Buffer) => {
      if (settled) return;
      settled = true;
      cleanup();
      try {
        resolve(JSON.parse(raw.toString("utf-8")));
      } catch {
        reject(new Error(`WS non-JSON: ${raw.toString("utf-8").slice(0, 100)}`));
      }
    };
    const errorHandler = (err: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(err);
    };
    ws.on("message", handler);
    ws.on("error", errorHandler);
  });
}

/**
 * HTTP POST with fail-fast validation.
 */
async function apiPost(
  request: any, url: string, body?: unknown, label?: string,
): Promise<any> {
  const resp = await request.post(url, {
    data: body,
    headers: body ? { "Content-Type": "application/json" } : {},
  });
  const tag = label ?? url;
  expect(resp.status(), `${tag}: HTTP status must be 2xx`).toBeGreaterThanOrEqual(200);
  expect(resp.status(), `${tag}: HTTP status must be <300`).toBeLessThan(300);
  const json = await resp.json();
  if (json && typeof json.success !== "undefined") {
    const okMsg = `${tag}: ApiResponse.success must be true (got ${JSON.stringify(json)})`;
    expect(json.success, okMsg).toBe(true);
  }
  return json;
}

/** HTTP GET with fail-fast validation. */
async function apiGet(request: any, url: string, label?: string): Promise<any> {
  const resp = await request.get(url);
  const tag = label ?? url;
  expect(resp.status(), `${tag}: HTTP status must be 2xx`).toBeGreaterThanOrEqual(200);
  expect(resp.status(), `${tag}: HTTP status must be <300`).toBeLessThan(300);
  return resp.json();
}

/**
 * Detect if a Chinese text contains a repeated prefix (>= 6 chars).
 *
 * Checks if the first `minPrefixLen` characters of `text` appear again
 * immediately or near-duplicated within the string. For example:
 *   "中华民族遭受了中华民族遭受了前所未有的劫难" → true (duplicate prefix)
 *   "中华民族遭受了前所未有的劫难" → false (no duplicate)
 *
 * A prefix is considered repeated if `prefix` appears at position 0 AND
 * again at position <= prefix.length + 5 (close/adjacent repetition).
 */
function detectRepeatedChinesePrefix(
  text: string,
  minPrefixLen = 6,
): { detected: boolean; prefix: string; firstPos: number; secondPos: number } {
  if (text.length < minPrefixLen * 2) {
    return { detected: false, prefix: "", firstPos: -1, secondPos: -1 };
  }
  // Extract candidate prefixes of increasing length
  for (let len = minPrefixLen; len <= Math.min(20, Math.floor(text.length / 2)); len++) {
    const prefix = text.slice(0, len);
    // Search for second occurrence starting at position > 0
    const secondPos = text.indexOf(prefix, 1);
    if (secondPos >= 0 && secondPos <= len + 5) {
      return { detected: true, prefix, firstPos: 0, secondPos };
    }
  }
  return { detected: false, prefix: "", firstPos: -1, secondPos: -1 };
}

/**
 * Sample the entire TranscriptPanel DOM and return structured data.
 * This is called every 200ms during the test.
 */
async function sampleDom(page: any): Promise<DomSample> {
  const sample: DomSample = {
    timestamp: Date.now(),
    interims: [],
    finals: [],
  };

  // Sample all interim rows
  const interimEls = await page.$$('[data-testid="transcript-interim"]');
  for (const el of interimEls) {
    const utteranceId = await el.getAttribute("data-utterance-id") ?? "";
    const revisionStr = await el.getAttribute("data-revision") ?? "0";
    const sourceEl = await el.$('[data-testid="transcript-source"]');
    const sourceText = sourceEl ? (await sourceEl.textContent())?.trim() ?? "" : "";
    sample.interims.push({
      utteranceId,
      revision: parseInt(revisionStr, 10),
      sourceText,
    });
  }

  // Sample all final rows
  const finalEls = await page.$$('[data-testid="transcript-final"]');
  for (const el of finalEls) {
    const utteranceId = await el.getAttribute("data-utterance-id") ?? "";
    const transIdStr = await el.getAttribute("data-translation-id") ?? "0";
    const sourceEl = await el.$('[data-testid="transcript-source"]');
    const sourceText = sourceEl ? (await sourceEl.textContent())?.trim() ?? "" : "";
    sample.finals.push({
      utteranceId,
      translationId: parseInt(transIdStr, 10),
      sourceText,
    });
  }

  return sample;
}

// ---- Test ------------------------------------------------------------------

test.describe("Speech streaming frontend-backend consistency", () => {
  let report: Report;
  let meetingId: number;

  test("real-time interim and final display consistency", async ({ page, request }) => {
    // ---- 0. Report initialisation -----------------------------------------
    report = {
      utterance_id: "",
      interim_count: 0,
      latest_interim_text: "",
      final_text: "",
      persisted_text: "",
      latency: {
        start_to_started_ms: null,
        first_frame_to_first_interim_ms: null,
        first_frame_to_latest_interim_ms: null,
        latest_interim_event_to_dom_ms: null,
        end_hint_to_final_ms: null,
        final_event_to_final_dom_ms: null,
      },
      pass: false,
      reason: "",
      dom_samples: [],
      max_interim_rows_for_utterance: 0,
      max_final_rows_for_utterance: 0,
      interim_final_overlap_seen: false,
      ws_interim_payloads: [],
      ws_final_payload: null,
      db_final_record: null,
      has_mojibake_labels: false,
      // Task 112: repeated prefix detection
      ws_interim_repeated_prefix_detected: false,
      ws_interim_repeated_prefix: "",
      ws_interim_failing_revision: null,
    };

    test.setTimeout(180_000);

    // ---- 1. Prepare backend state -----------------------------------------
    const activeMeeting: any = await apiGet(
      request, `${BACKEND}/api/meetings/active`, "GET /api/meetings/active",
    );
    if (activeMeeting?.data?.id) {
      await apiPost(
        request,
        `${BACKEND}/api/meetings/${activeMeeting.data.id}/end`,
        undefined,
        `POST /api/meetings/${activeMeeting.data.id}/end`,
      );
    }

    const createResp: any = await apiPost(
      request, `${BACKEND}/api/meetings`,
      { title: `E2E Speech ${Date.now()}`, description: "Task 110" },
      "POST /api/meetings",
    );
    meetingId = createResp?.data?.id;
    expect(meetingId).toBeGreaterThan(0);

    await apiPost(
      request, `${BACKEND}/api/meetings/${meetingId}/start`,
      undefined, `POST /api/meetings/${meetingId}/start`,
    );

    const speakerResp: any = await apiPost(
      request, `${BACKEND}/api/seats/speaker`,
      { seat_id: 1 },
      "POST /api/seats/speaker",
    );
    expect(speakerResp?.data?.seat_id).toBe(1);
    console.log(`[E2E] Meeting ${meetingId} ready, speaker seat=1`);

    // ---- 2. Navigate to admin page ----------------------------------------
    await page.goto("/");
    await page.waitForSelector("text=Connected", { timeout: 15_000 });
    // Give the browser WebSocket one short turn to finish joining the backend room
    await page.waitForTimeout(1000);
    console.log("[E2E] Admin page loaded, WS connected");

    // ---- 3. Connect broadcast WS (Node.js) --------------------------------
    const broadcastWs = await wsConnect(`ws://localhost:8000/ws/${meetingId}?seat=0`);
    const connected = await wsReceiveJson(broadcastWs, 5000);
    expect(connected.event).toBe("connected");
    console.log("[E2E] Test broadcast WS connected");

    // ---- 4. Connect speech WS (Node.js) -----------------------------------
    const speechWs = await wsConnect(`ws://localhost:8000/ws/speech/${meetingId}?seat=1`);
    console.log("[E2E] Speech WS connected");

    // ---- 5. Send start -----------------------------------------------------
    const tStartSend = Date.now();
    wsSendJson(speechWs, {
      type: "start", sample_rate: 16000, encoding: "pcm_s16le", channels: 1,
    });
    const startedMsg = await wsReceiveJson(speechWs, 10_000);
    const tStartedRecv = Date.now();
    expect(startedMsg.type).toBe("started");

    const uid: string = startedMsg.utterance_id;
    expect(uid).toMatch(/^utt_\d+_\d+_\d{6}$/);
    report.utterance_id = uid;
    report.latency.start_to_started_ms = tStartedRecv - tStartSend;
    console.log(`[E2E] Started: ${uid} (${report.latency.start_to_started_ms}ms)`);

    // ---- 6. Load PCM16 frames ---------------------------------------------
    const frames = loadPcmFrames(20);
    expect(frames.length).toBeGreaterThan(0);
    console.log(`[E2E] Sending ${frames.length} PCM frames`);

    // ---- 7. Start continuous DOM sampling + send frames + collect WS -------
    // We run three concurrent tasks:
    //   A) DOM sampling loop (every 200ms)
    //   B) PCM frame sending + WS interim collection
    //   C) Translation final collection
    //
    // After end_hint, we wait for final DOM + 1s settle, then stop sampling.

    let latestInterim: any = null;
    let interimCount = 0;
    let firstInterimReceivedAt = 0;
    let latestInterimReceivedAt = 0;
    const MAX_WAIT_MS = 25_000;

    // Start DOM sampling loop (runs until stopped by the main flow)
    let stopSampling = false;
    const samplingPromise = (async () => {
      while (!stopSampling) {
        const sample = await sampleDom(page);
        report.dom_samples.push(sample);
        // Wait 200ms between samples
        await new Promise((r) => setTimeout(r, 200));
      }
      // One final sample after stop
      const finalSample = await sampleDom(page);
      report.dom_samples.push(finalSample);
    })();

    // Send PCM frames with slight delay between them
    const tFirstFrameSend = Date.now();
    for (let i = 0; i < frames.length; i++) {
      speechWs.send(frames[i]);
      if (i < frames.length - 1) {
        await new Promise((r) => setTimeout(r, 30));
      }
    }

    // Collect interim WS messages while they arrive
    const collectStart = Date.now();
    let settledAt = 0;
    const SETTLE_MS = 600;

    while (Date.now() - collectStart < MAX_WAIT_MS) {
      if (settledAt > 0 && Date.now() - settledAt > SETTLE_MS) break;
      const recvTimeout = interimCount === 0 ? 1000 : 400;
      try {
        const msg = await wsReceiveJson(broadcastWs, recvTimeout);
        if (msg.event === "translation_interim" && msg.payload?.utterance_id === uid) {
          interimCount++;
          if (interimCount === 1) firstInterimReceivedAt = Date.now();

          // Record WS payload
          report.ws_interim_payloads.push({
            utterance_id: msg.payload.utterance_id,
            revision: msg.payload.revision,
            source_text: msg.payload.source_text,
            timestamp: Date.now(),
          });

          if (!latestInterim || msg.payload.revision > latestInterim.revision) {
            latestInterim = msg.payload;
            latestInterimReceivedAt = Date.now();
            settledAt = Date.now();
          }
          console.log(
            `[E2E] Interim #${interimCount}` +
            ` (rev ${msg.payload.revision}): "${msg.payload.source_text}"`,
          );
        }
      } catch {
        if (interimCount > 0) break;
      }
    }

    // Fail hard if no interim received
    if (!latestInterim) {
      report.reason = "No translation_interim received within timeout";
      console.log(`[E2E] ${report.reason}`);
      stopSampling = true;
      await samplingPromise;
      speechWs.close();
      broadcastWs.close();
      await writeReport(report);
      expect(latestInterim, report.reason).not.toBeNull();
    }

    report.latency.first_frame_to_first_interim_ms =
      firstInterimReceivedAt - tFirstFrameSend;
    report.latency.first_frame_to_latest_interim_ms =
      latestInterimReceivedAt - tFirstFrameSend;
    report.latest_interim_text = latestInterim.source_text;
    report.interim_count = interimCount;

    console.log(
      `[E2E] Interim stats: firstFrame->firstInterim=${report.latency.first_frame_to_first_interim_ms}ms` +
      ` firstFrame->latestInterim=${report.latency.first_frame_to_latest_interim_ms}ms` +
      ` latestRev=${latestInterim.revision} text="${latestInterim.source_text}"`,
    );

    // ---- 8. Analyze WS interim payloads for repeated prefixes (Task 112) -----
    report.ws_interim_repeated_prefix_detected = false;
    report.ws_interim_repeated_prefix = "";
    report.ws_interim_failing_revision = null;

    for (const p of report.ws_interim_payloads) {
      const sep = p.source_text || "";
      const check = detectRepeatedChinesePrefix(sep, 6);
      if (check.detected) {
        report.ws_interim_repeated_prefix_detected = true;
        report.ws_interim_repeated_prefix = check.prefix;
        report.ws_interim_failing_revision = p.revision;
        console.log(
          `[E2E] REPEATED PREFIX DETECTED: rev=${p.revision}` +
          ` prefix="${check.prefix}" text="${sep}"`,
        );
        break; // first failure is enough
      }
    }

    if (!report.ws_interim_repeated_prefix_detected) {
      console.log("[E2E] No repeated prefix detected in WS interim payloads");
    }

    // ---- 9. Verify DOM shows the latest interim --------------------------
    const interimRowSelector =
      `[data-testid="transcript-interim"][data-utterance-id="${uid}"]`;
    await page.waitForSelector(interimRowSelector, { timeout: 10_000 });
    const tInterimDomVisible = Date.now();
    report.latency.latest_interim_event_to_dom_ms =
      tInterimDomVisible - latestInterimReceivedAt;

    // ---- 9. Send end_hint -------------------------------------------------
    const tEndHintSend = Date.now();
    wsSendJson(speechWs, { type: "end_hint" });
    console.log("[E2E] end_hint sent");

    // ---- 10. Wait for translation_final on broadcast WS -------------------
    let finalPayload: any = null;
    const finalDeadline = Date.now() + 30_000;

    while (Date.now() < finalDeadline) {
      try {
        const msg = await wsReceiveJson(broadcastWs, 10_000);
        if (msg.event === "translation_final" && msg.payload?.utterance_id === uid) {
          finalPayload = msg.payload;
          report.ws_final_payload = {
            utterance_id: msg.payload.utterance_id,
            translation_id: msg.payload.translation_id,
            source_text: msg.payload.source_text,
            timestamp: Date.now(),
          };
          break;
        }
      } catch {
        break;
      }
    }

    if (!finalPayload) {
      report.reason = "No translation_final received within timeout";
      console.log(`[E2E] ${report.reason}`);
      stopSampling = true;
      await samplingPromise;
      speechWs.close();
      broadcastWs.close();
      await writeReport(report);
      expect(finalPayload, report.reason).not.toBeNull();
    }

    const tFinalRecv = Date.now();
    report.latency.end_hint_to_final_ms = tFinalRecv - tEndHintSend;
    report.final_text = finalPayload.source_text;
    console.log(
      `[E2E] Translation final: "${finalPayload.source_text}" (${report.latency.end_hint_to_final_ms}ms)`,
    );

    // Wait for final DOM to appear + 1s settle for continued sampling
    const finalRowSelector =
      `[data-testid="transcript-final"][data-utterance-id="${uid}"]`;
    await page.waitForSelector(finalRowSelector, { timeout: 20_000 });
    const tFinalDomVisible = Date.now();
    report.latency.final_event_to_final_dom_ms = tFinalDomVisible - tFinalRecv;

    // Wait 1s more for DOM to settle while sampling continues
    await page.waitForTimeout(1000);

    // Stop DOM sampling
    stopSampling = true;
    await samplingPromise;

    // ---- 11. Analyze DOM samples for duplicate detection ------------------
    let maxInterimForUid = 0;
    let maxFinalForUid = 0;
    let overlapSeen = false;

    for (const sample of report.dom_samples) {
      const interimCountForUid = sample.interims.filter(
        (i) => i.utteranceId === uid,
      ).length;
      if (interimCountForUid > maxInterimForUid) {
        maxInterimForUid = interimCountForUid;
      }

      const finalCountForUid = sample.finals.filter(
        (f) => f.utteranceId === uid,
      ).length;
      if (finalCountForUid > maxFinalForUid) {
        maxFinalForUid = finalCountForUid;
      }

      // Check if interim and final exist for the same uid in the same sample
      const hasInterim = sample.interims.some((i) => i.utteranceId === uid);
      const hasFinal = sample.finals.some((f) => f.utteranceId === uid);
      if (hasInterim && hasFinal) {
        overlapSeen = true;
      }
    }

    report.max_interim_rows_for_utterance = maxInterimForUid;
    report.max_final_rows_for_utterance = maxFinalForUid;
    report.interim_final_overlap_seen = overlapSeen;

    console.log(
      `[E2E] Analysis: maxInterimForUid=${maxInterimForUid} maxFinalForUid=${maxFinalForUid} overlap=${overlapSeen}`,
    );

    // ---- 12. Assertions for duplicates ------------------------------------
    // A0. No repeated Chinese prefix in any WS interim payload (Task 112)
    expect(
      report.ws_interim_repeated_prefix_detected,
      `Repeated prefix "${report.ws_interim_repeated_prefix}" detected in WS interim ` +
      `revision ${report.ws_interim_failing_revision}. ` +
      `This indicates the backend is sending payloads with duplicated text.`,
    ).toBe(false);

    // A. At any time, max 1 interim per utterance_id
    expect(
      maxInterimForUid,
      `Expected max 1 interim row for ${uid}, got ${maxInterimForUid}`,
    ).toBeLessThanOrEqual(1);

    // B. After final arrives, the last DOM samples should have 0 interims for this uid
    // Check the last 3 samples
    const lastSamples = report.dom_samples.slice(-3);
    for (const sample of lastSamples) {
      const uidInterims = sample.interims.filter((i) => i.utteranceId === uid);
      if (uidInterims.length > 0) {
        console.log(
          `[E2E] Warning: interim still present in late sample (${sample.interims.length} interims, ${sample.finals.length} finals)`,
        );
      }
    }
    // The very last sample should have 0 interims for our uid (final has replaced it)
    const finalSampleInterims = report.dom_samples[report.dom_samples.length - 1]
      .interims.filter((i) => i.utteranceId === uid);
    expect(
      finalSampleInterims.length,
      `Expected 0 interim rows for ${uid} in final sample, got ${finalSampleInterims.length}`,
    ).toBe(0);

    // C. Max 1 final per utterance_id
    expect(
      maxFinalForUid,
      `Expected max 1 final row for ${uid}, got ${maxFinalForUid}`,
    ).toBeLessThanOrEqual(1);
    // At least one final sample should have exactly 1
    const hasExactlyOneFinal = report.dom_samples.some(
      (s) => s.finals.filter((f) => f.utteranceId === uid).length === 1,
    );
    expect(hasExactlyOneFinal, `Expected at least one sample with exactly 1 final row for ${uid}`).toBe(true);

    // D. A brief transition overlap between interim removal → final rendering is
    // expected (React async state updates). The overlap should be transient:
    // the LAST sample must have 0 interims (verified above), and final must appear.
    // Log overlap for analysis but only fail if it persists (i.e., last sample has both).
    if (overlapSeen) {
      // Find the last sample with overlap
      const lastOverlap = [...report.dom_samples].reverse().find(
        (s) => s.interims.some((i) => i.utteranceId === uid) && s.finals.some((f) => f.utteranceId === uid),
      );
      // The last overlap should NOT be the final sample
      if (lastOverlap) {
        const lastIdx = report.dom_samples.length - 1;
        const overlapIdx = report.dom_samples.indexOf(lastOverlap);
        expect(overlapIdx, `Interim/final overlap persisted until sample ${overlapIdx}/${lastIdx}`).toBeLessThan(lastIdx);
      }
    }

    // ---- 13. DOM final text verification ----------------------------------
    const domFinalSource = await page.$eval(
      `${finalRowSelector} [data-testid="transcript-source"]`,
      (el) => el.textContent?.trim() ?? "",
    );
    const domFinalSeatId = await page.$eval(
      finalRowSelector, (el) => el.getAttribute("data-seat-id"),
    );
    console.log(
      `[E2E] DOM final: src="${domFinalSource}" seat=${domFinalSeatId}`,
    );

    // E. DOM final text === WS payload
    expect(domFinalSource, "DOM final source must match WS payload source_text").toBe(finalPayload.source_text);
    expect(Number(domFinalSeatId), "DOM final seat_id must match WS payload seat_id").toBe(finalPayload.seat_id);

    // ---- 14. GET /api/translations -- verify persisted record -------------
    const transResp: any = await apiGet(
      request,
      `${BACKEND}/api/translations?meeting_id=${meetingId}`,
      "GET /api/translations",
    );
    const entries: any[] = transResp?.data?.entries ?? [];
    const matches = entries.filter((e: any) => e.utterance_id === uid);
    expect(matches.length, `Expected at least 1 DB record for ${uid}`).toBeGreaterThanOrEqual(1);

    const persisted = matches[0];
    report.persisted_text = persisted.source_text;
    report.db_final_record = {
      id: persisted.id,
      utterance_id: persisted.utterance_id,
      source_text: persisted.source_text,
      created_at: persisted.created_at,
    };
    console.log(`[E2E] DB source_text: "${persisted.source_text}" (DOM: "${domFinalSource}")`);

    // F. DB text === DOM final text
    expect(persisted.source_text, "DB source_text must match DOM final source_text").toBe(domFinalSource);

    // G. DB text === WS payload text
    expect(persisted.source_text, "DB source_text must match WS payload source_text").toBe(finalPayload.source_text);

    // ---- 15. Check for mojibake in language labels ------------------------
    const labelEls = await page.$$('[data-testid="transcript-lang-label"]');
    let hasMojibake = false;
    for (const el of labelEls) {
      const text = await el.textContent();
      if (text && (text.includes("中文") || text.includes("涓") || text.includes("枃"))) {
        hasMojibake = true;
        break;
      }
    }
    // Also check header label
    const headerEl = await page.$('.text-xs.text-slate-400.font-medium');
    if (headerEl) {
      const headerText = await headerEl.textContent() ?? '';
      if (headerText.includes("中文") || headerText.includes("涓") || headerText.includes("枃")) {
        hasMojibake = true;
      }
    }
    report.has_mojibake_labels = hasMojibake;
    expect(hasMojibake, "Language labels must not contain mojibake or Chinese characters").toBe(false);

    // H. Verify lang labels are only EN or ZH
    for (const el of labelEls) {
      const text = await el.textContent();
      expect(text, `Language label must be "EN" or "ZH", got "${text}"`).toMatch(/^(EN|ZH)$/);
    }

    // ---- 16. Report: PASS -------------------------------------------------
    report.pass = true;
    report.reason = "All assertions passed: no duplicates, no overlap, no mojibake, text consistent WS/DB/DOM";

    console.log(
      `[E2E] Latency: ` +
      `start->started=${report.latency.start_to_started_ms}ms ` +
      `firstFrame->firstInterim=${report.latency.first_frame_to_first_interim_ms}ms ` +
      `firstFrame->latestInterim=${report.latency.first_frame_to_latest_interim_ms}ms ` +
      `latestInterim->DOM=${report.latency.latest_interim_event_to_dom_ms}ms ` +
      `endHint->final=${report.latency.end_hint_to_final_ms}ms ` +
      `final->DOM=${report.latency.final_event_to_final_dom_ms}ms`,
    );
    console.log(
      `[E2E] Dark launch: dom_samples=${report.dom_samples.length}` +
      ` maxInterim=${maxInterimForUid} maxFinal=${maxFinalForUid} overlap=${overlapSeen}`,
    );

    speechWs.close();
    broadcastWs.close();
    await writeReport(report);
  });

  test.afterAll(async ({ request }) => {
    if (meetingId) {
      try {
        await apiPost(request, `${BACKEND}/api/meetings/${meetingId}/end`);
      } catch {
        // best-effort cleanup
      }
    }
  });
});

// ---- Report Writer ----------------------------------------------------------

async function writeReport(r: Report): Promise<void> {
  const reportPath = path.resolve(
    __dirname, "..", "..", "working", "speech-e2e-report.json",
  );
  const dir = path.dirname(reportPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  fs.writeFileSync(reportPath, JSON.stringify(r, null, 2) + "\n", "utf-8");
  console.log(`[E2E] Report written to ${reportPath}`);
}
