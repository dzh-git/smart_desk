/**
 * Task 6 E2E — 低优先级但明确的前端问题修复
 *
 * 覆盖：
 * 1. 语音模型 preload 按钮
 * 2. 同名参会人投票使用 attendeeId
 * 3. 大屏端无 active meeting 自动轮询感知会议开始
 *
 * > ⚠️ Task 7 修正：座位端字幕历史已从「按 seat 过滤」改为
 * > 「全会议公开字幕历史」。座位端默认不再传 seat_id，
 * > 因此本测试中原有的 seat_id URL 断言已更新。
 * > API 的 `fetchTranslations(meetingId, seatId?)` 可选能力仍保留。
 *
 * Prerequisites:
 *   - Backend: http://localhost:8000 (ENABLE_DEMO_SEAT_API=true, ENABLE_DEMO_SEED=true)
 *   - Frontend: http://localhost:5173 (dev server, VITE_ENABLE_DEMO_CONTROLS=true)
 *   - Playwright config auto-starts frontend via webServer
 *
 * API usage: Only for cleanup (end leftover meetings) and creating attendees
 * for same-name test (UI cannot create duplicate name attendees reliably).
 */
import { test, expect } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8000";

test.describe("Task 6 — Low Priority Frontend Fixes", () => {
  let meetingId: number;

  test("Low-priority fixes: display polling, same-name vote, preload, seat translation", async ({ browser, request }) => {
    // ═══ 0. API Setup: end leftover meeting ════════════════════════════════
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      meetingId = activeJson.data.id;
      await request.post(`${BACKEND}/api/meetings/${meetingId}/end`);
    }

    // Verify cleanup
    const checkResp = await request.get(`${BACKEND}/api/meetings/active`);
    expect((await checkResp.json()).data).toBeNull();

    // ═══ 1. Open /display — verify waiting state ═══════════════════════
    const displayCtx = await browser.newContext();
    const displayPage = await displayCtx.newPage();
    await displayPage.goto("/display", { waitUntil: "networkidle" });

    // Verify "Waiting for Meeting" is shown (no active meeting)
    await expect(displayPage.getByText("Waiting for Meeting")).toBeVisible({ timeout: 15000 });

    // ═══ 2. Open /admin — create + start meeting ═══════════════════════
    const adminCtx = await browser.newContext();
    const adminPage = await adminCtx.newPage();
    await adminPage.goto("/admin", { waitUntil: "networkidle" });

    await expect(adminPage.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create pending meeting
    await adminPage.locator('[placeholder="Meeting title"]').fill("Task 6 E2E Meeting");
    await adminPage.getByRole("button", { name: /create pending meeting/i }).click();
    await adminPage.waitForTimeout(500);

    await expect(adminPage.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });

    // Start meeting
    await adminPage.getByRole("button", { name: /start meeting/i }).click();
    await adminPage.waitForTimeout(1500);

    await expect(adminPage.getByText("Task 6 E2E Meeting").first()).toBeVisible({ timeout: 15000 });

    // Capture meeting ID
    const meetingIdText = await adminPage.locator("text=ID").first().textContent();
    meetingId = parseInt(meetingIdText?.replace("ID ", "") ?? "0", 10);
    expect(meetingId).toBeGreaterThan(0);

    // ═══ 3. Verify /display polls and shows new meeting ════════════════
    // Display should auto-detect the active meeting via polling
    await displayPage.waitForTimeout(9000); // Allow up to 7s poll + 2s load

    await expect(displayPage.getByText("Task 6 E2E Meeting")).toBeVisible({ timeout: 15000 });
    await expect(displayPage.getByText("Waiting for Meeting")).not.toBeVisible();

    // Verify no more polling: display should keep showing active meeting
    await expect(displayPage.getByText("Task 6 E2E Meeting")).toBeVisible();

    // ═══ 4. Speech preload button check ════════════════════════════════
    await adminPage.bringToFront();

    // Preload button should be visible in active meeting
    const preloadBtn = adminPage.getByRole("button", { name: /preload speech model/i });
    await expect(preloadBtn).toBeVisible({ timeout: 5000 });

    // Click preload — verify loading/success/error feedback
    await preloadBtn.click();
    await adminPage.waitForTimeout(1000);

    // One of these should appear (success or error; loading is immediate)
    const preloadSuccess = adminPage.getByText("Preload triggered");
    const preloadFailed = adminPage.getByText("Preload failed");
    await expect(
      preloadSuccess.or(preloadFailed)
    ).toBeVisible({ timeout: 5000 });

    // ═══ 5. Create two same-name attendees + create vote ═══════════════
    // Use API to create attendees with same name (UI can't do duplicate names)
    await request.post(`${BACKEND}/api/meetings/${meetingId}/attendees`, {
      data: { name: "Same Name", title: "First" },
    });
    await request.post(`${BACKEND}/api/meetings/${meetingId}/attendees`, {
      data: { name: "Same Name", title: "Second" },
    });

    // Create a vote via UI
    await adminPage.locator('[placeholder="Vote title..."]').first().fill("Task 6 Vote");
    await adminPage.locator('[placeholder="Option 1"]').first().fill("Choice A");
    await adminPage.locator('[placeholder="Option 2"]').first().fill("Choice B");
    await adminPage.getByRole("button", { name: /create vote/i }).click();
    await adminPage.waitForTimeout(1000);

    await expect(adminPage.getByRole("button", { name: /close vote/i })).toBeVisible({ timeout: 10000 });

    // ═══ 6. Open /seat/1 — occupy, check in, verify vote submission ════
    const seatCtx = await browser.newContext();
    const seatPage = await seatCtx.newPage();
    await seatPage.goto("/seat/1", { waitUntil: "networkidle" });

    await expect(seatPage.getByText("Task 6 E2E Meeting").first()).toBeVisible({ timeout: 15000 });

    // Occupy Seat (Demo)
    const occupyBtn = seatPage.getByRole("button", { name: /occupy seat/i });
    await expect(occupyBtn).toBeVisible({ timeout: 10000 });
    await occupyBtn.click();
    await seatPage.waitForTimeout(1000);

    // Check-in: select "Same Name (First)" attendee (first one)
    await expect(seatPage.getByText(/Check-in Required/i).first()).toBeVisible({ timeout: 10000 });

    // Click the first "Same Name" attendee in the list
    const sameNameBtns = seatPage.locator('button:has-text("Same Name")');
    await expect(sameNameBtns.first()).toBeVisible({ timeout: 5000 });
    await sameNameBtns.first().click();
    await seatPage.waitForTimeout(300);

    // Confirm check-in
    await seatPage.getByRole("button", { name: /confirm check-in/i }).click();
    await seatPage.waitForTimeout(1500);

    // Verify checked in
    await expect(seatPage.getByText("Checked In")).toBeVisible({ timeout: 10000 });

    // Active Vote should be visible
    await expect(seatPage.getByText("Active Vote").first()).toBeVisible({ timeout: 10000 });

    // Select vote option and submit
    await seatPage.locator('button:has-text("Choice A")').first().click();
    await seatPage.waitForTimeout(300);

    const submitBtn = seatPage.getByRole("button", { name: /submit vote/i });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();
    await seatPage.waitForTimeout(1500);

    // Verify "Your vote" appears (vote submitted via attendeeId, not name lookup)
    await expect(seatPage.getByText("Your vote").first()).toBeVisible({ timeout: 10000 });
    await expect(seatPage.getByText("Your choice:")).toBeVisible();

    // ═══ 7. Verify seat translation request is meeting-wide (no seat_id) ════════════
    // Navigate to seat page fresh to trigger data fetching; set up request
    // listener before reload so we capture the API call.
    const transRequestPromise = seatPage.waitForRequest((req) =>
      req.url().includes("/api/translations") && req.method() === "GET"
    );
    await seatPage.goto("/seat/1", { waitUntil: "networkidle" });
    const transRequest = await transRequestPromise;
    // Task 7: The URL must NOT include seat_id for /seat/1 (meeting-wide)
    expect(transRequest.url()).not.toContain("seat_id");
    expect(transRequest.url()).toContain("meeting_id=");

    // Re-occupy and check-in (seat may have reset during navigation)
    await seatPage.waitForTimeout(500);
    const reOccupyBtn = seatPage.getByRole("button", { name: /occupy seat/i });
    if (await reOccupyBtn.isVisible()) {
      await reOccupyBtn.click();
      await seatPage.waitForTimeout(1000);
      const reAttendee = seatPage.locator('button:has-text("Same Name")').first();
      await reAttendee.waitFor({ state: "visible", timeout: 5000 });
      await reAttendee.click();
      await seatPage.waitForTimeout(300);
      await seatPage.getByRole("button", { name: /confirm check-in/i }).click();
      await seatPage.waitForTimeout(1500);
    }
    await expect(seatPage.getByText("Checked In").first()).toBeVisible({ timeout: 10000 });

    // ═══ 8. Close vote + end meeting ════════════════════════════════════
    await adminPage.bringToFront();

    // Close vote
    const closeBtn = adminPage.getByRole("button", { name: /close vote/i });
    await expect(closeBtn).toBeVisible({ timeout: 10000 });
    await closeBtn.click();
    await adminPage.waitForTimeout(1000);

    // End meeting
    adminPage.once("dialog", (d) => d.accept());
    await adminPage.getByRole("button", { name: /end meeting/i }).click();
    await adminPage.waitForTimeout(2000);

    // ═══ 9. Verify admin ended meeting view ═════════════════════════════
    await expect(adminPage.getByText("Meeting Ended").first()).toBeVisible({ timeout: 15000 });
    await expect(adminPage.getByText("Task 6 E2E Meeting").first()).toBeVisible();
    await expect(adminPage.getByText("Task 6 Vote").first()).toBeVisible();
    await expect(adminPage.getByRole("button", { name: /new meeting/i })).toBeVisible();

    // Write operations hidden
    await expect(adminPage.getByRole("button", { name: /end meeting/i })).not.toBeVisible();
    await expect(adminPage.getByRole("button", { name: /preload speech model/i })).not.toBeVisible();

    // ═══ 10. Verify display preserves ended meeting results ════════════
    await displayPage.waitForTimeout(2000);
    await expect(displayPage.getByText("Meeting Ended")).toBeVisible({ timeout: 15000 });
    await expect(displayPage.getByText(/Results are preserved below/)).toBeVisible();
    await expect(displayPage.getByText("Task 6 Vote").first()).toBeVisible({ timeout: 5000 });

    // Display should NOT show "Waiting for Meeting" — ended meeting is preserved
    await expect(displayPage.getByText("Waiting for Meeting")).not.toBeVisible();

    // ═══ 11. Verify display results persist after refresh ═══════════════
    await displayPage.reload({ waitUntil: "networkidle" });
    await expect(displayPage.getByText("Meeting Ended")).toBeVisible({ timeout: 15000 });
    await expect(displayPage.getByText("Task 6 Vote").first()).toBeVisible({ timeout: 5000 });

    // ═══ 12. Verify seat: after meeting ended ═══════════════════════════
    await seatPage.reload({ waitUntil: "networkidle" });
    await expect(seatPage.getByText("Waiting for Meeting")).toBeVisible({ timeout: 15000 });
    await expect(seatPage.getByRole("button", { name: /confirm check-in/i })).not.toBeVisible();
    await expect(seatPage.getByText("Active Vote")).not.toBeVisible();
    await expect(seatPage.getByText("Service Request")).not.toBeVisible();

    // ═══ 13. Cleanup ════════════════════════════════════════════════════
    await adminCtx.close();
    await seatCtx.close();
    await displayCtx.close();
  });
});
