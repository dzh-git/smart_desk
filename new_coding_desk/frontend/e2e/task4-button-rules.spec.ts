/**
 * Task 4 E2E — Unified Button Enable/Disable Rules
 *
 * 核心设计原则：
 *   - API 只用于环境清理
 *   - 所有核心用户流程通过真实 UI 点击完成
 *   - 串行执行确保数据一致性
 *   - 每个测试独立导航到页面（但依赖后端持久状态）
 *
 * Prerequisites:
 *   - Backend: localhost:8000 (ENABLE_DEMO_SEAT_API=true, ENABLE_DEMO_SEED=true)
 *   - Frontend: localhost:5173 (dev server, VITE_ENABLE_DEMO_CONTROLS=true)
 */

import { test, expect } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8000";

test.describe("Task 4 — Unified Button Rules", () => {
  test.describe.configure({ mode: "serial" });

  // ── 1. API: 环境清理 + 创建参会人 ──────────────────────────────────────────

  test("1. API cleanup: end any leftover active meeting and prepare", async ({ request }) => {
    // End any active meeting
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      await request.post(`${BACKEND}/api/meetings/${activeJson.data.id}/end`);
    }
    const checkResp = await request.get(`${BACKEND}/api/meetings/active`);
    const checkJson = await checkResp.json();
    expect(checkJson.data).toBeNull();
  });

  // ── 2. Admin: no_meeting → 只允许创建会议 ─────────────────────────────────────

  test("2. admin: no_meeting — only Create Pending Meeting, no End/Create Vote", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    await expect(page.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create Pending Meeting button: disabled when title empty
    const createBtn = page.getByRole("button", { name: /create pending meeting/i });
    await expect(createBtn).toBeVisible();
    await expect(createBtn).toBeDisabled();

    // End Meeting/Hidden buttons should NOT exist
    await expect(page.getByRole("button", { name: /end meeting/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /create vote/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /close vote/i })).not.toBeVisible();
    await expect(page.getByText("Current Phase:")).not.toBeVisible();
  });

  // ── 3. Admin: 创建 pending meeting → meeting_created → 启动 → meeting_active ──

  test("3. admin: create pending meeting, start — verify button states at each step", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // -- meeting_created phase --
    await page.locator('[placeholder="Meeting title"]').fill("Task 4 Button Test");
    const createBtn = page.getByRole("button", { name: /create pending meeting/i });
    await expect(createBtn).toBeEnabled();
    await createBtn.click();
    await page.waitForTimeout(500);

    // Pending Meeting card visible with Start Meeting
    await expect(page.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });
    const startBtn = page.getByRole("button", { name: /start meeting/i });
    await expect(startBtn).toBeEnabled();

    // In meeting_created: End Meeting, Create Vote should not be visible
    await expect(page.getByRole("button", { name: /end meeting/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /create vote/i })).not.toBeVisible();

    // -- transition to meeting_active --
    await startBtn.click();
    await page.waitForTimeout(1500);

    // Now active meeting UI should appear
    await expect(page.getByText("Task 4 Button Test").first()).toBeVisible({ timeout: 15000 });

    // End Meeting visible and enabled
    const endBtn = page.getByRole("button", { name: /end meeting/i });
    await expect(endBtn).toBeVisible();
    await expect(endBtn).toBeEnabled();

    // Phase selector visible
    await expect(page.getByText("Current Phase:")).toBeVisible();
    await expect(page.getByRole("button", { name: "General" })).toBeVisible();

    // Create Vote form visible (no open vote yet)
    await expect(page.getByPlaceholder("Vote title...")).toBeVisible();
  });

  // ── 4. Admin: 创建投票 + 验证不能创建第二个 open 投票 ──────────────────────────

  test("4. admin: create vote — verify cannot create second open vote", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("Task 4 Button Test").first()).toBeVisible({ timeout: 15000 });

    // Create vote
    await page.locator('[placeholder="Vote title..."]').first().fill("E2E Test Vote");
    await page.locator('[placeholder="Option 1"]').first().fill("Choice A");
    await page.locator('[placeholder="Option 2"]').first().fill("Choice B");
    await page.getByRole("button", { name: /create vote/i }).click();
    await page.waitForTimeout(1000);

    // Vote should appear
    await expect(page.getByText("E2E Test Vote").first()).toBeVisible({ timeout: 10000 });

    // Create Vote form should be hidden (existing open vote blocks it)
    await expect(page.getByPlaceholder("Vote title...")).not.toBeVisible();
  });

  // ── 5. Seat: 未签到 → 不能投票、服务、语音 ─────────────────────────────────────

  test("5. seat: not checked in — vote/service/speech not visible", async ({ page }) => {
    await page.goto("/seat/1", { waitUntil: "networkidle" });
    await expect(page.getByText("Task 4 Button Test").first()).toBeVisible({ timeout: 15000 });

    // Not checked in: no vote section, no service section
    await expect(page.getByText("Active Vote")).not.toBeVisible();
    await expect(page.getByText("Service Request")).not.toBeVisible();
  });

  // ── 6. Seat: Demo 占座 + 签到 + 提交投票 ─────────────────────────────────────

  test("6. seat: demo occupy + check in + submit vote", async ({ page, request }) => {
    // Create an attendee via API (needed for check-in)
    const meetingResp = await request.get(`${BACKEND}/api/meetings/active`);
    const meetingJson = await meetingResp.json();
    const meetingTitle = meetingJson.data?.title;

    await request.post(`${BACKEND}/api/meetings/${meetingJson.data.id}/attendees`, {
      data: { name: "E2E Tester", title: "QA" },
    });

    await page.goto("/seat/1", { waitUntil: "networkidle" });
    await expect(page.getByText(meetingTitle).first()).toBeVisible({ timeout: 15000 });

    // Occupy Seat (Demo) if vacant
    const occupyBtn = page.getByRole("button", { name: /occupy seat/i });
    if (await occupyBtn.isVisible()) {
      await occupyBtn.click();
      await page.waitForTimeout(1000);
    }

    // Check-in: select attendee
    await expect(page.getByText(/Check-in Required/i).first()).toBeVisible({ timeout: 10000 });
    const attendeeBtn = page.locator('button:has-text("E2E Tester")').first();
    await expect(attendeeBtn).toBeVisible({ timeout: 5000 });
    await attendeeBtn.click();
    await page.waitForTimeout(300);

    await page.getByRole("button", { name: /confirm check-in/i }).click();
    await page.waitForTimeout(1500);

    await expect(page.getByText("Checked In")).toBeVisible({ timeout: 10000 });

    // -- Submit vote --
    await expect(page.getByText("Active Vote").first()).toBeVisible({ timeout: 10000 });

    // Select vote option
    await page.locator('button:has-text("Choice A")').first().click();
    await page.waitForTimeout(300);

    // Submit Vote button should be enabled and clickable
    const submitBtn = page.getByRole("button", { name: /submit vote/i });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();
    await page.waitForTimeout(1500);

    // Verify vote was recorded
    await expect(page.getByText("Your vote")).toBeVisible({ timeout: 10000 });
  });

  // ── 7. Admin: 关闭投票 ──────────────────────────────────────────────────────

  test("7. admin: close vote — results visible", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("Task 4 Button Test").first()).toBeVisible({ timeout: 15000 });

    // Close Vote button should be visible
    const closeBtn = page.getByRole("button", { name: /close vote/i });
    await expect(closeBtn).toBeVisible({ timeout: 10000 });
    await closeBtn.click();
    await page.waitForTimeout(1000);

    // After closing, vote shows as "Closed"
    await expect(page.getByText("Closed").first()).toBeVisible({ timeout: 10000 });

    // Create Vote form should reappear
    await expect(page.getByPlaceholder("Vote title...")).toBeVisible({ timeout: 5000 });
  });

  // ── 8. Seat: 投票关闭后 → 不能继续提交 ────────────────────────────────────────

  test("8. seat: after vote closed — cannot submit/update", async ({ page }) => {
    await page.goto("/seat/1", { waitUntil: "networkidle" });
    await expect(page.getByText("Checked In").first()).toBeVisible({ timeout: 15000 });

    // Should show "Final Result" instead of "Active Vote"
    await expect(page.getByText("Final Result").first()).toBeVisible({ timeout: 10000 });

    // Submit/Update Vote should NOT be visible
    await expect(page.getByRole("button", { name: /submit vote/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /update vote/i })).not.toBeVisible();

    // Vote option buttons should be disabled
    const choiceBtn = page.locator('button:has-text("Choice A")').first();
    await expect(choiceBtn).toBeDisabled();
  });

  // ── 9. Admin: 结束会议 → 只读视图 ────────────────────────────────────────────

  test("9. admin: end meeting — read-only ended view", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("Task 4 Button Test").first()).toBeVisible({ timeout: 15000 });

    // End meeting
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: /end meeting/i }).click();
    await page.waitForTimeout(2000);

    // Ended meeting view
    await expect(page.getByText("Meeting Ended").first()).toBeVisible({ timeout: 15000 });

    // Vote results still visible
    await expect(page.getByText("E2E Test Vote").first()).toBeVisible();

    // Write operations hidden
    await expect(page.getByRole("button", { name: /end meeting/i })).not.toBeVisible();
    await expect(page.getByPlaceholder("Vote title...")).not.toBeVisible();
    await expect(page.getByPlaceholder("Attendee name")).not.toBeVisible();
    await expect(page.getByPlaceholder("Agenda title")).not.toBeVisible();
    await expect(page.getByText("Current Phase:")).not.toBeVisible();

    // Read-only actions available (ended view has New Meeting, not Refresh)
    await expect(page.getByRole("button", { name: /new meeting/i })).toBeVisible();
  });

  // ── 10. Seat: 会议结束后 → 不能签到、投票、服务、语音 ──────────────────────────

  test("10. seat: after meeting ended — no actions", async ({ page }) => {
    await page.goto("/seat/1", { waitUntil: "networkidle" });

    // Should show Waiting for Meeting
    await expect(page.getByText("Waiting for Meeting")).toBeVisible({ timeout: 15000 });

    // All action UI gone
    await expect(page.getByRole("button", { name: /confirm check-in/i })).not.toBeVisible();
    await expect(page.getByText("Active Vote")).not.toBeVisible();
    await expect(page.getByText("Final Result")).not.toBeVisible();
    await expect(page.getByText("Service Request")).not.toBeVisible();
    await expect(page.getByRole("button", { name: /start/i })).not.toBeVisible();
  });

  // ── 11. Display: 只有 Refresh ───────────────────────────────────────────────

  test("11. display: only Refresh button, no write operations", async ({ page }) => {
    await page.goto("/display", { waitUntil: "networkidle" });

    // Should show meeting results
    await expect(page.getByRole("button", { name: /refresh/i })).toBeVisible();

    // No write buttons should exist
    await expect(page.getByRole("button", { name: /create vote/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /close vote/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /end meeting/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /start meeting/i })).not.toBeVisible();
  });
});
