import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";
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
    await seat.getByTestId("seat-tab-captions").click();
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

async function expectSpatialReady(page: Page) {
  const stage = page.getByTestId("spatial-stage");
  await expect(stage).toHaveAttribute("data-renderer", "webgl2", { timeout: 20_000 });
  await expect(stage.locator("canvas")).toBeVisible();
}

async function verifyFullscreen(page: Page, button: Locator, unavailable: Locator) {
  await page.bringToFront();
  await button.click();
  await expect.poll(async () =>
    await page.evaluate(() => document.fullscreenElement === document.documentElement)
    || await unavailable.isVisible(),
  ).toBe(true);
  if (!(await unavailable.isVisible())) {
    await button.click();
    await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
  }
}

test("prepare, operate, and review a nine-seat meeting across devices", async ({ browser, baseURL, request }) => {
  const englishPCM = process.env.SMARTDESK_PRESENTATION_ENGLISH_PCM;
  const checkSpatial = process.env.SMARTDESK_PLAYWRIGHT_WEBGL === "software";
  test.setTimeout(checkSpatial || englishPCM ? 240_000 : 120_000);
  const softwareViewport = { width: 1280, height: 850 };
  const controller = await browser.newContext({
    baseURL, viewport: checkSpatial ? softwareViewport : { width: 1600, height: 1000 },
  });
  const guest = await browser.newContext({ baseURL, viewport: { width: 1280, height: 800 } });
  const displayDevice = await browser.newContext({
    baseURL, viewport: checkSpatial ? softwareViewport : { width: 1920, height: 1080 },
  });
  if (checkSpatial) {
    // Multiple SwiftShader views share the test host with the speech models.
    await Promise.all([controller, guest, displayDevice].map((context) => context.addInitScript(() => {
      localStorage.setItem("smartdesk.spatial.preferences.v1", JSON.stringify({ quality: "low", reducedMotion: true }));
    })));
  }
  const admin = await controller.newPage();
  const host = await controller.newPage();
  const seat = await guest.newPage();
  const display = await displayDevice.newPage();
  admin.on("dialog", (dialog) => void dialog.accept());
  const title = "SmartDesk 路线图会议";
  const topics = ["第一阶段 · 范围评审", "第二阶段 · 交付计划", "第三阶段 · 风险回顾"];

  await Promise.all([admin.goto("/admin"), seat.goto("/seat/2"), display.goto("/display")]);
  await expect(seat.getByText(/Waiting for Meeting/)).toBeVisible();
  await expect(display.getByTestId("display-focus")).toHaveAttribute("data-focus", "waiting");
  await admin.getByPlaceholder(/Meeting title/).fill(title);
  await admin.getByRole("button", { name: /Create Pending Meeting/ }).click();
  await expect(admin.getByRole("heading", { name: title })).toBeVisible();

  await admin.getByPlaceholder(/Attendee name/).fill("临时参会人");
  await admin.getByPlaceholder(/Title/).fill("测试职务");
  await admin.getByRole("button", { name: /Add attendee/i }).click();
  await expect(admin.getByText("测试职务", { exact: true })).toBeVisible();
  await admin.getByTestId("conference-seat-4").click();
  const assignment = admin.getByTestId("seat-assignment-select");
  await assignment.selectOption({ label: "临时参会人 · 未绑定人脸" });
  await expect(admin.getByText(/临时参会人 · 座位 4/)).toBeVisible();
  await assignment.selectOption("");
  await expect(admin.getByText(/临时参会人 · 座位 4/)).toHaveCount(0);
  await admin.getByRole("button", { name: /Delete attendee 临时参会人/ }).click();
  await expect(admin.getByText("临时参会人", { exact: true })).toHaveCount(0);

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
  await seat.getByTestId("seat-options").click();
  await seat.getByRole("button", { name: /Vacate Seat \(Demo\)/ }).click();
  await expect(seat.getByTestId("face-access-gate")).toBeVisible();
  await seat.getByRole("button", { name: /Demo Check-in/ }).click();
  await expect(seat.getByText("Checked In", { exact: true })).toBeVisible();

  await host.goto("/host");
  await expect(host.getByText("演示模式 / Demo Mode", { exact: true })).toBeVisible();
  if (checkSpatial) {
    await Promise.all([admin, host, seat, display].map(expectSpatialReady));
  }
  const secondSeat = await guest.newPage();
  await secondSeat.goto("/seat/3");
  if (checkSpatial) await expectSpatialReady(secondSeat);
  await expect(secondSeat.getByRole("button", { name: /Demo Check-in/ })).toBeVisible();
  await admin.getByTestId("conference-seat-3").click();
  await admin.getByTestId("manual-admit-button").click();
  await expect(secondSeat.getByText("Checked In", { exact: true })).toBeVisible();
  const meetingId: number = (await (await request.get("/api/meetings/active")).json()).data.id;

  const popup = admin.waitForEvent("popup");
  await admin.getByRole("link", { name: "会议大屏" }).click();
  const linkedDisplay = await popup;
  await expect(linkedDisplay).toHaveURL(/\/display$/);
  await expect(linkedDisplay.getByRole("heading", { name: title })).toBeVisible();
  await linkedDisplay.close();
  const displayRefresh = display.waitForResponse((response) => new URL(response.url()).pathname === "/api/meetings/active");
  await display.getByRole("button", { name: /Refresh/ }).click();
  expect((await displayRefresh).ok()).toBe(true);
  await verifyFullscreen(display, display.getByRole("button", { name: /Fullscreen/i }), display.getByText(/无法切换全屏/));

  await admin.getByLabel("更多会议操作 / More meeting actions").click();
  await expect(admin.getByTestId("host-display-control")).toBeVisible();
  if (process.env.SMARTDESK_PRESENTATION_EXPECT_HARDWARE_OFFLINE === "true") {
    await expect(admin.getByTestId("display-agent-state")).toContainText("CONTROL SERVICE OFFLINE");
    for (const app of ["powerpoint", "solidworks", "smartdesk"]) {
      await expect(admin.getByTestId(`activate-${app}`)).toBeDisabled();
    }
  }
  await admin.getByLabel("更多会议操作 / More meeting actions").click();

  await seat.getByTestId("seat-screen-entry").click();
  await expect(seat).toHaveURL(/\/screen$/);
  await expect(seat.getByTestId("screen-view")).toBeVisible();
  await expect(seat.getByTestId("screen-retry")).toBeEnabled();
  const screenStatus = seat.waitForResponse((response) => new URL(response.url()).pathname === "/api/host-display/status");
  await seat.getByTestId("screen-retry").click();
  expect((await screenStatus).ok()).toBe(true);
  await seat.getByText(/Playback Details/).click();
  if (process.env.SMARTDESK_PRESENTATION_EXPECT_HARDWARE_OFFLINE === "true") {
    await expect(seat.getByTestId("agent-offline")).toBeVisible();
    await expect(seat.getByTestId("stream-iframe")).toHaveCount(0);
  }
  await seat.getByText(/Playback Details/).click();
  await verifyFullscreen(seat, seat.getByTestId("screen-fullscreen"), seat.getByText(/Fullscreen Unavailable/));
  const tryPlayback = seat.getByRole("button", { name: /Try playback/ });
  if (await tryPlayback.isVisible()) {
    await tryPlayback.click();
    await expect(seat.getByTestId("stream-iframe")).toHaveAttribute("src", /:8889\/screen\?/);
  }
  await seat.getByRole("link", { name: /Back/ }).click();
  await expect(seat).toHaveURL(/\/seat\/2$/);
  await expect(seat.getByText("Checked In", { exact: true })).toBeVisible();

  await admin.getByRole("button", { name: "议程 / Agenda" }).click();
  for (const topic of topics) {
    await admin.getByPlaceholder(/TOPIC TITLE/).fill(topic);
    await admin.getByRole("button", { name: "添加 / ADD", exact: true }).click();
    await expect(admin.getByRole("button", { name: new RegExp(topic) })).toBeVisible();
  }
  const expectCurrentTopic = async (topic: string) => {
    await expect(seat.getByText(topic, { exact: true })).toBeVisible();
    await expect(display.getByTestId("display-focus").getByRole("heading", { name: topic })).toBeVisible();
  };
  await admin.getByRole("button", { name: new RegExp(topics[0]) }).click();
  await admin.getByRole("button", { name: /SET CURRENT/ }).click();
  await expectCurrentTopic(topics[0]);
  await admin.getByRole("button", { name: /ADVANCE$/ }).click();
  await expectCurrentTopic(topics[1]);
  await admin.getByRole("button", { name: new RegExp(`${topics[1]}.*Active`, "i") }).click();
  await admin.getByRole("button", { name: new RegExp(`${topics[0]}.*Done`, "i") }).click();
  await expect(admin.getByText("已完成议题 / COMPLETED", { exact: true }).last()).toBeVisible();
  await expect(admin.getByRole("button", { name: /SET CURRENT/ })).toHaveCount(0);
  await admin.getByRole("button", { name: /COMPLETE$/ }).click();
  await expect(admin.getByRole("button", { name: new RegExp(`${topics[1]}.*Done`, "i") })).toBeVisible();
  await expect(seat.getByRole("heading", { name: /No Active Topic/i })).toBeVisible();
  await admin.getByRole("button", { name: new RegExp(topics[2]) }).click();
  await admin.getByRole("button", { name: /SET CURRENT/ }).click();
  await expectCurrentTopic(topics[2]);
  await admin.getByRole("button", { name: /SKIP$/ }).click();
  await expect(admin.getByRole("button", { name: new RegExp(`${topics[2]}.*Skipped`, "i") })).toBeVisible();

  await admin.getByRole("button", { name: /Overview/i }).click();
  await admin.getByTestId("conference-seat-2").click();
  await admin.getByRole("button", { name: /Set Speaker/ }).click();
  await expect(seat.getByRole("region", { name: "麦克风 / Microphone" })).toBeVisible();
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
  await expect(secondSeat.getByRole("region", { name: "麦克风 / Microphone" })).toBeVisible();
  await expect(seat.getByRole("region", { name: "麦克风 / Microphone" })).toHaveCount(0);
  if (englishPCM && baseURL) {
    finals.push(await verifySpeech(secondSeat, request, baseURL, meetingId, 3, "en", englishPCM));
  }
  await admin.getByRole("button", { name: "清除发言 / Clear" }).click();
  await expect(secondSeat.getByRole("region", { name: "麦克风 / Microphone" })).toHaveCount(0);

  await admin.getByRole("button", { name: "投票 / Voting" }).click();
  await admin.getByRole("button", { name: /Create Vote/i }).click();
  await seat.getByTestId("seat-tab-vote").click();
  await seat.getByRole("button", { name: "同意 / Approve", exact: true }).click();
  await seat.getByRole("button", { name: /Submit Vote/ }).click();
  const displayVote = display.getByTestId("display-vote-panel");
  const approve = displayVote.getByRole("listitem").filter({ hasText: "同意 / Approve" });
  await expect(approve).toContainText("1 票");
  await expect(approve).toContainText("100%");
  if (checkSpatial) {
    await expect(admin.getByTestId("spatial-stage")).toHaveAttribute("data-phase", "vote");
    await expect(display.getByTestId("spatial-stage")).toHaveAttribute("data-phase", "vote");
  }
  await seat.getByRole("button", { name: "反对 / Reject", exact: true }).click();
  await seat.getByRole("button", { name: /Update Vote/ }).click();
  await expect(seat.getByText("Your choice:", { exact: true })).toBeVisible();
  const reject = displayVote.getByRole("listitem").filter({ hasText: "反对 / Reject" });
  await expect(reject).toContainText("1 票");
  await expect(reject).toContainText("100%");
  await admin.getByRole("button", { name: "Close Vote" }).click();
  await expect(display.getByText("Vote Result", { exact: true })).toBeVisible();
  await expect(seat.getByRole("button", { name: /Submit Vote|Update Vote/ })).toHaveCount(0);

  await seat.getByTestId("seat-tab-service").click();
  await seat.getByRole("button", { name: /Coffee/i }).click();
  await admin.getByRole("button", { name: "服务 / Services" }).click();
  await expect(admin.getByRole("button", { name: "Resolve" })).toBeVisible();
  await seat.getByRole("button", { name: /取消 \/ Cancel/ }).click();
  await expect(admin.getByText("Cancelled", { exact: true })).toBeVisible();
  await expect(admin.getByRole("button", { name: "Resolve" })).toHaveCount(0);
  await seat.getByRole("button", { name: /Water/i }).click();
  await admin.getByRole("button", { name: "Resolve" }).click();
  await expect(admin.getByText("Resolved", { exact: true })).toBeVisible();
  await expect(seat.getByRole("button", { name: /Water/i })).toBeEnabled();

  await admin.getByLabel("更多会议操作 / More meeting actions").click();
  await admin.getByRole("button", { name: /End Meeting/i }).click();
  await expect(display.getByText("Meeting Ended", { exact: true })).toBeVisible();
  await expect(seat.getByText(/Waiting for Meeting/)).toBeVisible();
  await expect(admin.getByText("Meeting Ended", { exact: true }).first()).toBeVisible();
  await expect(host.getByText("Meeting Ended", { exact: true }).first()).toBeVisible();
  await expect(admin.getByRole("button", { name: /End Meeting/i })).toHaveCount(0);
  if (checkSpatial) {
    await expect(display.getByTestId("spatial-stage")).toHaveAttribute("data-phase", "complete");
  }
  await display.reload();
  await expect(display.getByText("Vote Result", { exact: true })).toBeVisible();
  await admin.getByRole("button", { name: "记录 / Records" }).click();
  for (const final of finals) {
    await expect(admin.locator(`[data-testid="transcript-final"][data-utterance-id="${final.utterance_id}"]`))
      .toContainText(final.translated_text);
  }

  await admin.getByRole("button", { name: /New Meeting/ }).click();
  await expect(admin.getByPlaceholder(/Meeting title/)).toBeVisible();
  const nextTitle = "SmartDesk 后续会议";
  await admin.getByPlaceholder(/Meeting title/).fill(nextTitle);
  await admin.getByRole("button", { name: /Create Pending Meeting/ }).click();
  await expect(admin.getByRole("heading", { name: nextTitle })).toBeVisible();
  await admin.getByRole("button", { name: /Start Meeting/ }).click();
  await expect(display.getByRole("heading", { name: nextTitle })).toBeVisible({ timeout: 15_000 });
  await expect(seat.getByText(/Waiting for host seat assignment/)).toBeVisible({ timeout: 15_000 });
  await admin.getByLabel("更多会议操作 / More meeting actions").click();
  await admin.getByRole("button", { name: /End Meeting/i }).click();
  await expect(admin.getByText("Meeting Ended", { exact: true }).first()).toBeVisible();

  await controller.close();
  await guest.close();
  await displayDevice.close();
});
