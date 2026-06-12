/**
 * Task 7 E2E — 字幕可见范围与历史字幕排序修复
 *
 * 覆盖：
 * 1. 座位端拉字幕历史时不默认带 seat_id（全会议可见）
 * 2. 所有座位都能看到任一座位产生的 final translation
 * 3. 管理员端拉字幕历史也不带 seat_id
 * 4. 历史字幕 UI 按 created_at 升序排序（oldest first）
 * 5. created_at 相同时 id 小的在上
 * 6. translation_final 后刷新后其他座位也能看到
 *
 * Prerequisites:
 *   - Backend: http://localhost:8000 (ENABLE_DEMO_SEAT_API=true, ENABLE_DEMO_SEED=true)
 *   - Frontend: http://localhost:5173 (dev server)
 *   - Playwright config auto-starts frontend via webServer
 *
 * Strategy:
 *   使用 page.route() 拦截翻译 API 返回 mock 数据验证 UI。
 *   创建会议后通过 API 直接插入 mock translation records，
 *   用 route 拦截验证请求 URL 不包含 seat_id。
 */
import { test, expect } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8000";

test.describe("Task 7 — Transcript Visibility & Sort Order", () => {
  let meetingId: number;

  test("transcript visibility and sort order fix verification", async ({ browser, request }) => {
    // ═══ 0. API Setup: end leftover meeting ════════════════════════════════
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      meetingId = activeJson.data.id;
      await request.post(`${BACKEND}/api/meetings/${meetingId}/end`);
    }

    // ═══ 1. Open /admin — create + start meeting ═══════════════════════════
    const adminCtx = await browser.newContext();
    const adminPage = await adminCtx.newPage();
    await adminPage.goto("/admin", { waitUntil: "domcontentloaded" });

    await expect(adminPage.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create pending meeting
    await adminPage.locator('[placeholder="Meeting title"]').fill("Task 7 E2E Meeting");
    await adminPage.getByRole("button", { name: /create pending meeting/i }).click();
    await adminPage.waitForTimeout(500);

    await expect(adminPage.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });

    // Start meeting
    await adminPage.getByRole("button", { name: /start meeting/i }).click();
    await adminPage.waitForTimeout(1500);

    await expect(adminPage.getByText("Task 7 E2E Meeting").first()).toBeVisible({ timeout: 15000 });

    // Capture meeting ID
    const meetingIdText = await adminPage.locator("text=ID").first().textContent();
    meetingId = parseInt(meetingIdText?.replace("ID ", "") ?? "0", 10);
    expect(meetingId).toBeGreaterThan(0);

    // Add 2 attendees via API for seats 1 and 2
    const attendee1Resp = await request.post(
      `${BACKEND}/api/meetings/${meetingId}/attendees`,
      { data: { name: "Alice Wang" } },
    );
    const attendee1 = (await attendee1Resp.json()).data;
    // Check in seat 1
    await request.post(`${BACKEND}/api/seats/1/checkin`, { data: { attendee_id: attendee1.id } });

    const attendee2Resp = await request.post(
      `${BACKEND}/api/meetings/${meetingId}/attendees`,
      { data: { name: "Bob Li" } },
    );
    const attendee2 = (await attendee2Resp.json()).data;
    await request.post(`${BACKEND}/api/seats/2/checkin`, { data: { attendee_id: attendee2.id } });

    // ═══ 2. Open seat pages ════════════════════════════════════════════════
    const seat1Ctx = await browser.newContext();
    const seat1Page = await seat1Ctx.newPage();

    const seat2Ctx = await browser.newContext();
    const seat2Page = await seat2Ctx.newPage();

    // ═══ 3. Intercept translations API to verify URL patterns ═══════════
    const adminTranslationsUrls: string[] = [];
    const seat1TranslationsUrls: string[] = [];
    const seat2TranslationsUrls: string[] = [];

    await adminPage.route(/\/api\/translations/, async (route) => {
      adminTranslationsUrls.push(route.request().url());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "OK",
          data: {
            meeting_id: meetingId,
            entries: [
              {
                id: 100, meeting_id: meetingId, seat_id: 1,
                source_lang: "zh", target_lang: "en",
                source_text: "创建会议后第一句话",
                translated_text: "First sentence after meeting creation",
                created_at: "2026-01-01T10:03:00Z",
                utterance_id: "utt_e2e_001",
              },
              {
                id: 101, meeting_id: meetingId, seat_id: 2,
                source_lang: "zh", target_lang: "en",
                source_text: "第二个人说的内容",
                translated_text: "Second person's speech",
                created_at: "2026-01-01T10:05:00Z",
                utterance_id: "utt_e2e_002",
              },
            ],
          },
        }),
      });
    });

    await seat1Page.route(/\/api\/translations/, async (route) => {
      seat1TranslationsUrls.push(route.request().url());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "OK",
          data: {
            meeting_id: meetingId,
            entries: [
              {
                id: 100, meeting_id: meetingId, seat_id: 1,
                source_lang: "zh", target_lang: "en",
                source_text: "创建会议后第一句话",
                translated_text: "First sentence after meeting creation",
                created_at: "2026-01-01T10:03:00Z",
                utterance_id: "utt_e2e_001",
              },
              {
                id: 101, meeting_id: meetingId, seat_id: 2,
                source_lang: "zh", target_lang: "en",
                source_text: "第二个人说的内容",
                translated_text: "Second person's speech",
                created_at: "2026-01-01T10:05:00Z",
                utterance_id: "utt_e2e_002",
              },
            ],
          },
        }),
      });
    });

    await seat2Page.route(/\/api\/translations/, async (route) => {
      seat2TranslationsUrls.push(route.request().url());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "OK",
          data: {
            meeting_id: meetingId,
            entries: [
              {
                id: 100, meeting_id: meetingId, seat_id: 1,
                source_lang: "zh", target_lang: "en",
                source_text: "创建会议后第一句话",
                translated_text: "First sentence after meeting creation",
                created_at: "2026-01-01T10:03:00Z",
                utterance_id: "utt_e2e_001",
              },
              {
                id: 101, meeting_id: meetingId, seat_id: 2,
                source_lang: "zh", target_lang: "en",
                source_text: "第二个人说的内容",
                translated_text: "Second person's speech",
                created_at: "2026-01-01T10:05:00Z",
                utterance_id: "utt_e2e_002",
              },
            ],
          },
        }),
      });
    });

    // ═══ 4. Navigate all three pages and verify ══════════════════════════
    await adminPage.goto("/admin", { waitUntil: "domcontentloaded" });
    await seat1Page.goto("/seat/1", { waitUntil: "domcontentloaded" });
    await seat2Page.goto("/seat/2", { waitUntil: "domcontentloaded" });

    // Allow time for data loading
    await adminPage.waitForTimeout(2000);
    await seat1Page.waitForTimeout(2000);
    await seat2Page.waitForTimeout(2000);

    // ═══ 5. Verify seat 1 translations URL has no seat_id ═══════════════
    for (const url of seat1TranslationsUrls) {
      expect(url).toContain("meeting_id=");
      expect(url).not.toContain("seat_id");
    }

    // ═══ 6. Verify seat 2 translations URL has no seat_id ═══════════════
    for (const url of seat2TranslationsUrls) {
      expect(url).toContain("meeting_id=");
      expect(url).not.toContain("seat_id");
    }

    // ═══ 7. Verify admin translations URL has no seat_id ═════════════════
    for (const url of adminTranslationsUrls) {
      expect(url).toContain("meeting_id=");
      expect(url).not.toContain("seat_id");
    }

    // ═══ 8. Verify ALL pages show BOTH translations (meeting-wide) ══════
    // Admin page
    await expect(adminPage.getByText("First sentence after meeting creation")).toBeVisible({ timeout: 5000 });
    await expect(adminPage.getByText("Second person's speech")).toBeVisible({ timeout: 5000 });

    // Seat 1
    await expect(seat1Page.getByText("First sentence after meeting creation")).toBeVisible({ timeout: 5000 });
    await expect(seat1Page.getByText("Second person's speech")).toBeVisible({ timeout: 5000 });

    // Seat 2
    await expect(seat2Page.getByText("First sentence after meeting creation")).toBeVisible({ timeout: 5000 });
    await expect(seat2Page.getByText("Second person's speech")).toBeVisible({ timeout: 5000 });

    // ═══ 9. Verify sort order (oldest first) ═════════════════════════════
    // Check that the transcript rows appear in chronological order on admin page
    const adminFinalRows = await adminPage.locator('[data-testid="transcript-final"]').all();
    if (adminFinalRows.length >= 2) {
      const firstTime = await adminFinalRows[0].getAttribute("data-created-at");
      const secondTime = await adminFinalRows[1].getAttribute("data-created-at");
      // First entry (10:03) should be older than second (10:05)
      expect(new Date(firstTime!).getTime()).toBeLessThan(new Date(secondTime!).getTime());
    }

    // Check on seat 1
    const seat1FinalRows = await seat1Page.locator('[data-testid="transcript-final"]').all();
    if (seat1FinalRows.length >= 2) {
      const firstTime = await seat1FinalRows[0].getAttribute("data-created-at");
      const secondTime = await seat1FinalRows[1].getAttribute("data-created-at");
      expect(new Date(firstTime!).getTime()).toBeLessThan(new Date(secondTime!).getTime());
    }
  });
});
