/**
 * Task 5 E2E — 完整会议流程验收测试
 *
 * 覆盖完整生命周期：无会议 → 创建 → 启动 → 议程讨论 → 投票 → 大屏显示 →
 * 关闭投票 → 结束会议 → 结束视图验证。
 *
 * 核心设计原则：
 *   - API 只用于环境清理（结束残留会议）和准备无法通过 UI 创建的数据（参会人）
 *   - 所有核心用户流程通过真实 UI 点击完成
 *   - 使用 browser fixtures 管理 admin / seat / display 多页面
 *   - /display 在会议结束前打开并保持，以验证 WebSocket 驱动的 ended path
 *
 * Prerequisites:
 *   - Backend: http://localhost:8000 (ENABLE_DEMO_SEAT_API=true, ENABLE_DEMO_SEED=true)
 *   - Frontend: http://localhost:5173 (dev server, VITE_ENABLE_DEMO_CONTROLS=true)
 *   - Playwright config auto-starts frontend via webServer
 */
import { test, expect } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8000";

test.describe("Task 5 — Full Meeting Flow Acceptance", () => {
  let meetingId: number;

  test("Full meeting lifecycle: admin → seat → display → end", async ({ browser, request }) => {
    // ═══ 0. API Setup ══════════════════════════════════════════════════════

    // End any leftover active meeting
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      meetingId = activeJson.data.id;
      await request.post(`${BACKEND}/api/meetings/${meetingId}/end`);
    }

    // Verify cleanup
    const checkResp = await request.get(`${BACKEND}/api/meetings/active`);
    expect((await checkResp.json()).data).toBeNull();

    // ═══ 1. Admin: create + start meeting ═════════════════════════════════

    const adminCtx = await browser.newContext();
    const adminPage = await adminCtx.newPage();
    await adminPage.goto("/admin", { waitUntil: "networkidle" });

    // Verify no meeting state
    await expect(adminPage.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create pending meeting via UI
    await adminPage.locator('[placeholder="Meeting title"]').fill("Full Acceptance Flow");
    await adminPage.getByRole("button", { name: /create pending meeting/i }).click();
    await adminPage.waitForTimeout(500);

    // Verify pending meeting card
    await expect(adminPage.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });

    // Start meeting via UI
    await adminPage.getByRole("button", { name: /start meeting/i }).click();
    await adminPage.waitForTimeout(1500);

    // Verify active meeting
    await expect(adminPage.getByText("Full Acceptance Flow").first()).toBeVisible({ timeout: 15000 });

    // Capture meeting ID from the page
    const meetingIdText = await adminPage.locator("text=ID").first().textContent();
    meetingId = parseInt(meetingIdText?.replace("ID ", "") ?? "0", 10);
    expect(meetingId).toBeGreaterThan(0);

    // ═══ 2. Admin: verify phase selector + switch to Agenda Discussion ════

    // Phase selector should be visible with default "General"
    await expect(adminPage.getByText("Current Phase:")).toBeVisible();
    await expect(adminPage.getByRole("button", { name: "General" })).toBeVisible();
    await expect(adminPage.getByRole("button", { name: "Agenda Discussion" })).toBeVisible();

    // Switch to Agenda Discussion
    await adminPage.getByRole("button", { name: "Agenda Discussion" }).click();
    await adminPage.waitForTimeout(500);
    await expect(adminPage.getByText("Agenda Discussion Mode")).toBeVisible();
    await expect(adminPage.getByText(/Agenda items are emphasised/)).toBeVisible();

    // ═══ 3. Admin: add an agenda item ═════════════════════════════════════

    await adminPage.locator('[placeholder="Agenda title"]').first().fill("Review Budget Proposal");
    await adminPage.getByRole("button", { name: /add agenda/i }).click();
    await adminPage.waitForTimeout(500);
    await expect(adminPage.getByText("Review Budget Proposal")).toBeVisible({ timeout: 10000 });

    // Switch back to General
    await adminPage.getByRole("button", { name: "General" }).click();
    await adminPage.waitForTimeout(500);
    await expect(adminPage.getByText("Agenda Discussion Mode")).not.toBeVisible();

    // ═══ 4. Admin: create a vote ══════════════════════════════════════════

    // Fill vote form
    await adminPage.locator('[placeholder="Vote title..."]').first().fill("Acceptance Test Vote");
    await adminPage.locator('[placeholder="Option 1"]').first().fill("Option Alpha");
    await adminPage.locator('[placeholder="Option 2"]').first().fill("Option Beta");

    // Create vote
    await adminPage.getByRole("button", { name: /create vote/i }).click();
    await adminPage.waitForTimeout(1000);

    // Verify vote was created — Close Vote button should appear
    await expect(adminPage.getByRole("button", { name: /close vote/i })).toBeVisible({ timeout: 10000 });

    // ═══ 5. Seat: open /seat/1, occupy, check in, submit vote ═════════════

    // Create an attendee via API (UI lacks stable attendee creation path in demo)
    const meetingFetchResp = await request.get(`${BACKEND}/api/meetings/active`);
    const meetingFetchJson = await meetingFetchResp.json();
    const activeMeetingId = meetingFetchJson.data.id;

    const attResp = await request.post(`${BACKEND}/api/meetings/${activeMeetingId}/attendees`, {
      data: { name: "Flow Tester", title: "QA" },
    });
    const attJson = await attResp.json();
    const attendeeId = attJson.data.id;
    expect(attendeeId).toBeGreaterThan(0);

    const seatCtx = await browser.newContext();
    const seatPage = await seatCtx.newPage();
    await seatPage.goto("/seat/1", { waitUntil: "networkidle" });

    // Verify seat page shows the meeting title
    await expect(seatPage.getByText("Full Acceptance Flow").first()).toBeVisible({ timeout: 15000 });

    // Occupy Seat (Demo) — button only visible with VITE_ENABLE_DEMO_CONTROLS=true
    const occupyBtn = seatPage.getByRole("button", { name: /occupy seat/i });
    await expect(occupyBtn).toBeVisible({ timeout: 10000 });
    await occupyBtn.click();
    await seatPage.waitForTimeout(1000);

    // Check-in: select attendee
    await expect(seatPage.getByText(/Check-in Required/i).first()).toBeVisible({ timeout: 10000 });

    // Click the attendee button
    const attendeeBtn = seatPage.locator('button:has-text("Flow Tester")').first();
    await expect(attendeeBtn).toBeVisible({ timeout: 5000 });
    await attendeeBtn.click();
    await seatPage.waitForTimeout(300);

    // Confirm check-in
    await seatPage.getByRole("button", { name: /confirm check-in/i }).click();
    await seatPage.waitForTimeout(1500);

    // Verify checked in
    await expect(seatPage.getByText("Checked In")).toBeVisible({ timeout: 10000 });

    // Active Vote should be visible
    await expect(seatPage.getByText("Active Vote").first()).toBeVisible({ timeout: 10000 });

    // Select vote option
    await seatPage.locator('button:has-text("Option Alpha")').first().click();
    await seatPage.waitForTimeout(300);

    // Submit vote
    const submitBtn = seatPage.getByRole("button", { name: /submit vote/i });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();
    await seatPage.waitForTimeout(1500);

    // Verify vote was recorded
    await expect(seatPage.getByText("Your vote").first()).toBeVisible({ timeout: 10000 });

    // ═══ 6. Display: open /display while meeting is active ════════════════

    const displayCtx = await browser.newContext();
    const displayPage = await displayCtx.newPage();
    await displayPage.goto("/display", { waitUntil: "networkidle" });

    // Verify display shows active meeting with open vote
    await expect(displayPage.getByText("Full Acceptance Flow")).toBeVisible({ timeout: 15000 });
    await expect(displayPage.getByText("Acceptance Test Vote")).toBeVisible({ timeout: 10000 });
    await expect(displayPage.getByText("Vote In Progress")).toBeVisible();
    await expect(displayPage.getByText("Option Alpha")).toBeVisible();
    await expect(displayPage.getByText("Option Beta")).toBeVisible();
    await expect(displayPage.getByText("Meeting Ended")).not.toBeVisible();

    // ═══ 7. Admin: close vote ═════════════════════════════════════════════

    await adminPage.bringToFront();

    const closeBtn = adminPage.getByRole("button", { name: /close vote/i });
    await expect(closeBtn).toBeVisible({ timeout: 10000 });
    await closeBtn.click();
    await adminPage.waitForTimeout(1000);

    // Verify close vote button is gone and create vote form reappears
    await expect(adminPage.getByRole("button", { name: /close vote/i })).not.toBeVisible({ timeout: 5000 });
    await expect(adminPage.getByPlaceholder("Vote title...")).toBeVisible({ timeout: 5000 });

    // ═══ 8. Display: verify closed vote ═══════════════════════════════════

    // After vote_closed WS event, display should update
    await displayPage.waitForTimeout(2000);

    // Verify display shows "Vote Result" (closed state)
    await expect(displayPage.getByText("Vote Result")).toBeVisible({ timeout: 15000 });

    // Vote title and options should still be visible
    await expect(displayPage.getByText("Acceptance Test Vote")).toBeVisible();
    await expect(displayPage.getByText("Option Alpha").first()).toBeVisible();
    await expect(displayPage.getByText("Option Beta").first()).toBeVisible();

    // ═══ 9. Admin: end meeting ════════════════════════════════════════════

    await adminPage.bringToFront();

    // Handle confirm dialog and click End Meeting
    adminPage.once("dialog", (d) => d.accept());
    await adminPage.getByRole("button", { name: /end meeting/i }).click();
    await adminPage.waitForTimeout(2000);

    // ═══ 10. Verify admin ended meeting view ═════════════════════════════

    // Ended meeting banner
    await expect(adminPage.getByText("Meeting Ended").first()).toBeVisible({ timeout: 15000 });
    await expect(adminPage.getByText("Full Acceptance Flow").first()).toBeVisible();

    // Vote results preserved
    await expect(adminPage.getByText("Acceptance Test Vote").first()).toBeVisible();
    await expect(adminPage.getByText("Option Alpha").first()).toBeVisible();
    await expect(adminPage.getByText("Option Beta").first()).toBeVisible();

    // Write operations hidden
    await expect(adminPage.getByRole("button", { name: /end meeting/i })).not.toBeVisible();
    await expect(adminPage.getByPlaceholder("Vote title...")).not.toBeVisible();
    await expect(adminPage.getByPlaceholder("Agenda title")).not.toBeVisible();
    await expect(adminPage.getByPlaceholder("Attendee name")).not.toBeVisible();
    await expect(adminPage.getByText("Current Phase:")).not.toBeVisible();

    // "New Meeting" button visible
    await expect(adminPage.getByRole("button", { name: /new meeting/i })).toBeVisible();

    // ═══ 11. Verify display shows meeting ended state ════════════════════

    await displayPage.waitForTimeout(2000);

    // Display should show meeting ended state (via WS event)
    await expect(displayPage.getByText("Meeting Ended")).toBeVisible({ timeout: 15000 });
    await expect(displayPage.getByText(/Results are preserved below/)).toBeVisible();

    // Vote results still visible
    await expect(displayPage.getByText("Acceptance Test Vote").first()).toBeVisible({ timeout: 5000 });

    // No empty states
    await expect(displayPage.getByText("Waiting for Meeting")).not.toBeVisible();
    await expect(displayPage.getByText("No votes yet")).not.toBeVisible();

    // ═══ 12. Verify display results persist after refresh ════════════════

    await displayPage.reload({ waitUntil: "networkidle" });

    await expect(displayPage.getByText("Meeting Ended")).toBeVisible({ timeout: 15000 });
    await expect(displayPage.getByText("Acceptance Test Vote").first()).toBeVisible({ timeout: 5000 });
    await expect(displayPage.getByText("Option Alpha").first()).toBeVisible();
    await expect(displayPage.getByText("Option Beta").first()).toBeVisible();

    // ═══ 13. Verify seat: after meeting ended ═════════════════════════════

    await seatPage.reload({ waitUntil: "networkidle" });

    // Should show "Waiting for Meeting" (no active meeting)
    await expect(seatPage.getByText("Waiting for Meeting")).toBeVisible({ timeout: 15000 });

    // All action UI should be gone
    await expect(seatPage.getByRole("button", { name: /confirm check-in/i })).not.toBeVisible();
    await expect(seatPage.getByText("Active Vote")).not.toBeVisible();
    await expect(seatPage.getByText("Final Result")).not.toBeVisible();
    await expect(seatPage.getByText("Service Request")).not.toBeVisible();
    await expect(seatPage.getByRole("button", { name: /start/i })).not.toBeVisible();

    // ═══ 14. Cleanup ═════════════════════════════════════════════════════

    await adminCtx.close();
    await seatCtx.close();
    await displayCtx.close();
  });
});
