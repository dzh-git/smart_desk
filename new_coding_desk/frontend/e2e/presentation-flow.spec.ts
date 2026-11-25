import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import WebSocket from "ws";

interface SpeechResult {
  utterance_id: string;
  source_lang: string;
  target_lang: string;
  source_text: string;
  translated_text: string;
  translation_status: string;
}

async function verifySpeech(
  seat: Page,
  request: APIRequestContext,
  baseURL: string,
  meetingId: number,
  seatId: number,
  language: "zh" | "en",
  path: string,
) {
  const wsURL = baseURL.replace(/^http/, "ws");
  const events: Array<{ event: string; payload: SpeechResult }> = [];
  const broadcast = new WebSocket(`${wsURL}/ws/${meetingId}?seat=0`);
  const uploader = new WebSocket(`${wsURL}/ws/speech/${meetingId}?seat=${seatId}`);
  let utteranceId = "";
  broadcast.on("message", (raw) => events.push(JSON.parse(raw.toString())));
  uploader.on("message", (raw) => {
    const message = JSON.parse(raw.toString());
    if (message.type === "started" && !utteranceId) utteranceId = message.utterance_id;
  });
  try {
    await expect.poll(() => events.some((event) => event.event === "connected")).toBe(true);
    await expect.poll(() => uploader.readyState).toBe(WebSocket.OPEN);
    uploader.send(JSON.stringify({
      type: "start", sample_rate: 16000, encoding: "pcm_s16le", channels: 1, language_mode: language,
    }));
    await expect.poll(() => utteranceId).not.toBe("");
    const pcm = await readFile(path);
    const gain = language === "zh" ? 2 : 1.2;
    for (let offset = 0; offset + 1 < pcm.length; offset += 2) {
      const sample = Math.round(pcm.readInt16LE(offset) * gain);
      pcm.writeInt16LE(Math.max(-32768, Math.min(32767, sample)), offset);
    }
    const frameBytes = 3200;
    for (let frame = 0; frame < 4; frame += 1) uploader.send(Buffer.alloc(frameBytes));
    for (let offset = 0; offset + frameBytes <= pcm.length; offset += frameBytes) {
      uploader.send(pcm.subarray(offset, offset + frameBytes));
      await delay(50);
    }
    const result = (name: string) => events.find((event) =>
      event.event === name && event.payload.utterance_id === utteranceId)?.payload;
    await expect.poll(() => result("translation_interim")?.source_lang, { timeout: 18_000 }).toBe(language);
    await expect(seat.locator(
      `[data-testid="live-caption"][data-seat-id="${seatId}"], [data-testid="live-lyrics"][data-seat-id="${seatId}"]`,
    ).first()).toBeVisible();

    uploader.send(JSON.stringify({ type: "end_hint" }));
    await expect.poll(() => result("translation_final")?.translation_status, { timeout: 60_000 }).toBe("ok");
    const final = result("translation_final")!;
    expect(final.source_lang).toBe(language);
    expect(final.target_lang).toBe(language === "zh" ? "en" : "zh");
    expect(final.translated_text).toMatch(language === "zh" ? /[A-Za-z]{2,}/ : /\p{Script=Han}/u);
    const finalRow = seat.locator(`[data-testid="transcript-final"][data-utterance-id="${utteranceId}"]`);
    await expect(finalRow).toHaveCount(1);
    await expect(finalRow).toContainText(final.translated_text);
    const history: SpeechResult[] = (await (await request.get(`/api/translations?meeting_id=${meetingId}`)).json()).data.entries;
    expect(history.find((item) => item.utterance_id === utteranceId)?.translated_text).toBe(final.translated_text);
    return final;
  } finally {
    uploader.close();
    broadcast.close();
  }
}

test.skip(
  process.env.SMARTDESK_PRESENTATION_E2E !== "true",
  "Requires the demo frontend and a dedicated FastAPI database without an active meeting.",
);

test("prepare, operate, and review a nine-seat meeting across devices", async ({ browser, baseURL, request }) => {
  const englishPCM = process.env.SMARTDESK_PRESENTATION_ENGLISH_PCM;
  test.setTimeout(englishPCM ? 240_000 : 120_000);
  const controller = await browser.newContext({ baseURL, viewport: { width: 1600, height: 1000 } });
  const guest = await browser.newContext({ baseURL, viewport: { width: 1280, height: 800 } });
  const displayDevice = await browser.newContext({ baseURL, viewport: { width: 1920, height: 1080 } });
  const admin = await controller.newPage();
  const host = await controller.newPage();
  const seat = await guest.newPage();
  const display = await displayDevice.newPage();
  admin.on("dialog", (dialog) => void dialog.accept());
  const title = "SmartDesk 路线图会议";
  const topics = ["第一阶段 · 范围评审", "第二阶段 · 交付计划", "第三阶段 · 风险回顾"];

  await Promise.all([admin.goto("/admin"), seat.goto("/seat/2"), display.goto("/display")]);
  await expect(seat.getByText(/Waiting for Meeting/)).toBeVisible();
  await expect(display.getByText("Waiting for Meeting")).toBeVisible();
  await admin.getByPlaceholder(/Meeting title/).fill(title);
  await admin.getByRole("button", { name: /Create Pending Meeting/ }).click();
  await expect(admin.getByRole("heading", { name: title })).toBeVisible();

  for (const [seatId, name] of [[2, "林安"], [3, "陈晨"]] as const) {
    await admin.getByPlaceholder(/Attendee name/).fill(name);
    await admin.getByRole("button", { name: /Add attendee/i }).click();
    await expect(admin.getByText(name, { exact: true })).toBeVisible();
    await admin.getByTestId(`conference-seat-${seatId}`).click();
    await admin.getByTestId("seat-assignment-select").selectOption({ label: `${name} · 未绑定人脸` });
    await expect(admin.getByText(new RegExp(`${name} · 座位 ${seatId}`))).toBeVisible();
  }
  await admin.reload();
  await expect(admin.getByText(/林安 · 座位 2/)).toBeVisible();
  await expect(admin.getByText(/陈晨 · 座位 3/)).toBeVisible();
  await admin.getByRole("button", { name: /Start Meeting/ }).click();
  await expect(admin.getByText(title, { exact: true }).first()).toBeVisible();
  await expect(admin.getByTestId("conference-seat-9")).toBeVisible();
  await expect(display.getByRole("heading", { name: title })).toBeVisible({ timeout: 15_000 });
  await expect(seat.getByText("林安", { exact: true })).toBeVisible({ timeout: 15_000 });
  await seat.getByRole("button", { name: /Demo Check-in/ }).click();
  await expect(seat.getByText("Checked In", { exact: true })).toBeVisible();
  await seat.reload();
  await expect(seat.getByText("Checked In", { exact: true })).toBeVisible();

  await host.goto("/host");
  await expect(host.getByText("演示模式 / Demo Mode", { exact: true })).toBeVisible();
  const secondSeat = await guest.newPage();
  await secondSeat.goto("/seat/3");
  await secondSeat.getByRole("button", { name: /Demo Check-in/ }).click();
  await expect(secondSeat.getByText("Checked In", { exact: true })).toBeVisible();
  const meetingId: number = (await (await request.get("/api/meetings/active")).json()).data.id;

  await admin.getByRole("button", { name: /Agenda & Vote/i }).click();
  for (const topic of topics) {
    await admin.getByPlaceholder(/TOPIC TITLE/).fill(topic);
    await admin.getByRole("button", { name: "添加 / ADD", exact: true }).click();
    await expect(admin.getByRole("button", { name: new RegExp(topic) })).toBeVisible();
  }
  for (const topic of topics) {
    await admin.getByRole("button", { name: new RegExp(topic) }).click();
    await admin.getByRole("button", { name: /SET CURRENT/ }).click();
    await expect(seat.getByText(topic, { exact: true })).toBeVisible();
    await expect(display.getByTestId("display-agenda-panel").getByText(topic, { exact: true })).toHaveCount(2);
  }
  await admin.getByRole("button", { name: /SKIP$/ }).click();
  await expect(admin.getByRole("button", { name: new RegExp(`${topics[2]}.*Skipped`, "i") })).toBeVisible();

  await admin.getByRole("button", { name: /Overview/i }).click();
  await admin.getByTestId("conference-seat-2").click();
  await admin.getByRole("button", { name: /Set Speaker/ }).click();
  await expect(seat.getByText("Speaking", { exact: true })).toBeVisible();
  const finals: SpeechResult[] = [];
  if (englishPCM && baseURL) {
    await expect.poll(async () => {
      const { data } = await (await request.get("/api/speech/status")).json();
      return data.ready && data.translation_model === "loaded";
    }, { timeout: 60_000 }).toBe(true);
    finals.push(await verifySpeech(seat, request, baseURL, meetingId, 2, "zh", "../tests/fixtures/speech_sample.pcm"));
  }
  await admin.getByTestId("conference-seat-3").click();
  await admin.getByRole("button", { name: /Set Speaker/ }).click();
  await expect(secondSeat.getByText("Speaking", { exact: true })).toBeVisible();
  await expect(seat.getByText("Speaking", { exact: true })).toHaveCount(0);
  if (englishPCM && baseURL) {
    finals.push(await verifySpeech(secondSeat, request, baseURL, meetingId, 3, "en", englishPCM));
  }

  await admin.getByRole("button", { name: /Agenda & Vote/i }).click();
  await admin.getByRole("button", { name: /Create Vote/i }).click();
  await seat.getByRole("button", { name: "同意 / Approve", exact: true }).click();
  await seat.getByRole("button", { name: /Submit Vote/ }).click();
  await expect(display.getByText(/1 票.*100%/)).toBeVisible();
  await seat.getByRole("button", { name: "反对 / Reject", exact: true }).click();
  await seat.getByRole("button", { name: /Update Vote/ }).click();
  await expect(seat.getByText("Your choice:", { exact: true })).toBeVisible();
  await admin.getByRole("button", { name: "Close Vote" }).click();
  await expect(display.getByText("Vote Result", { exact: true })).toBeVisible();
  await expect(seat.getByRole("button", { name: /Submit Vote|Update Vote/ })).toHaveCount(0);

  await seat.getByRole("button", { name: /Coffee/i }).click();
  await admin.getByRole("button", { name: /Service & Records/i }).click();
  await admin.getByRole("button", { name: "Resolve" }).click();
  await expect(admin.getByText("Resolved", { exact: true })).toBeVisible();

  await admin.getByRole("button", { name: /End Meeting/i }).click();
  await expect(display.getByText("Meeting Ended", { exact: true })).toBeVisible();
  await expect(seat.getByText(/Waiting for Meeting/)).toBeVisible();
  await expect(admin.getByText("Meeting Ended", { exact: true }).first()).toBeVisible();
  await expect(host.getByText("Meeting Ended", { exact: true }).first()).toBeVisible();
  await expect(admin.getByRole("button", { name: /End Meeting/i })).toHaveCount(0);
  await display.reload();
  await expect(display.getByText("Vote Result", { exact: true })).toBeVisible();
  for (const final of finals) {
    await expect(admin.locator(`[data-testid="transcript-final"][data-utterance-id="${final.utterance_id}"]`))
      .toContainText(final.translated_text);
  }

  await controller.close();
  await guest.close();
  await displayDevice.close();
});
