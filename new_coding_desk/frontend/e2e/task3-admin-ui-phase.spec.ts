/**
 * Task 3 E2E — 主持人端 Workspace 内容分组（原阶段选择 UI 已移除）
 *
 * 核心设计原则：
 *   - API 只用于环境清理（结束残留会议）
 *   - 所有核心用户流程通过真实 UI 点击完成
 *   - 每个测试独立导航到页面，不依赖前序测试的页面状态
 *   - 串行执行确保数据一致性
 *
 * 注意：Current Phase 模块和 General / Agenda Discussion 阶段选择 UI 已完全移除。
 * 改为 AdminWorkspace 内容分组机制（本地状态，不是会议阶段）。
 *
 * Prerequisites:
 *   - Backend: localhost:8000 (ENABLE_DEMO_SEAT_API=true, ENABLE_DEMO_SEED=true)
 *   - Frontend: localhost:5173 (dev server, VITE_ENABLE_DEMO_CONTROLS=true)
 */

import { test, expect } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8000";

test.describe("Task 3 — Admin Workspace (replaces Phase Selector)", () => {
  test.describe.configure({ mode: "serial" });

  // ── Helper ───────────────────────────────────────────────────────────────────
  /** Wait until active-meeting indicators are fully loaded. */
  async function waitActiveAdmin(page: import("@playwright/test").Page) {
    await expect(page.getByRole("button", { name: /结束会议/i })).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("button", { name: /会议总览/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /议程与投票/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /服务与记录/i })).toBeVisible();
  }

  // ── 1. API: 环境清理 ──────────────────────────────────────────────────────

  test("1. API cleanup: end any leftover active meeting", async ({ request }) => {
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      await request.post(`${BACKEND}/api/meetings/${activeJson.data.id}/end`);
    }
    const checkResp = await request.get(`${BACKEND}/api/meetings/active`);
    const checkJson = await checkResp.json();
    expect(checkJson.data).toBeNull();
  });

  // ── 2. UI: 创建会议 + 启动 + 验证 Current Phase 已移除 + 三个 Workspace 按钮存在 ──

  test("2. UI: create pending meeting, start, verify Current Phase removed and three workspace buttons exist", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    await expect(page.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create pending meeting
    await page.locator('[placeholder="Meeting title"]').fill("Workspace E2E");
    await page.getByRole("button", { name: /create pending meeting/i }).click();
    await page.waitForTimeout(500);

    await expect(page.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });

    // Start the meeting
    await page.getByRole("button", { name: /start meeting/i }).click();

    // Wait for reliable active-meeting indicators
    await waitActiveAdmin(page);

    // Current Phase must NOT be visible
    await expect(page.getByText("当前阶段")).toHaveCount(0);
    await expect(page.getByText("CURRENT PHASE")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "General" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Agenda Discussion" })).toHaveCount(0);
  });

  // ── 3. UI: 默认 workspace 为 overview ──────────────────────────────────────

  test("3. UI: default workspace is overview — shows conference table and attendees", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Default should be overview: conference table visible
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).toBeVisible();

    // Attendees section visible
    await expect(page.getByText("参会人员")).toBeVisible();

    // "议程控制台" must not appear in overview workspace (it's inside conditionally-rendered PanelCard)
    await expect(page.getByText("议程控制台")).toHaveCount(0);
  });

  // ── 4. UI: 切换到 agenda_vote workspace ────────────────────────────────────

  test("4. UI: switch to agenda_vote — shows agenda panels, hides conference table", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Switch to agenda_vote
    await page.getByRole("button", { name: /议程与投票/i }).click();

    // Conference table should NOT be visible
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).not.toBeVisible();

    // Create Vote form should be visible (no open vote)
    await expect(page.getByPlaceholder("Vote title...")).toBeVisible();

    // Agenda title input should be visible
    await expect(page.getByPlaceholder("输入议题标题 / TOPIC TITLE").first()).toBeVisible();
  });

  // ── 5. UI: 在 agenda_vote 下添加议程 ───────────────────────────────────────

  test("5. UI: add agenda item in agenda_vote workspace", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Switch to agenda_vote
    await page.getByRole("button", { name: /议程与投票/i }).click();

    // Add agenda item
    await page.locator('[placeholder="输入议题标题 / TOPIC TITLE"]').first().fill("Discuss Budget");
    await page.getByRole("button", { name: /添加/i }).click();

    await expect(page.getByText("Discuss Budget")).toBeVisible({ timeout: 10000 });
  });

  // ── 6. UI: 切回 overview ──────────────────────────────────────────────────

  test("6. UI: switch back to overview — conference table and attendees return", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Switch to agenda_vote first
    await page.getByRole("button", { name: /议程与投票/i }).click();
    await page.waitForTimeout(300);
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).not.toBeVisible();

    // Switch back to overview
    await page.getByRole("button", { name: /会议总览/i }).click();
    await page.waitForTimeout(300);

    // Conference table should return
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).toBeVisible();
  });

  // ── 7. UI: 创建投票 ───────────────────────────────────────────────────────

  test("7. UI: create vote unaffected by workspace switch", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Switch to agenda_vote workspace
    await page.getByRole("button", { name: /议程与投票/i }).click();

    // Fill vote form
    await page.locator('[placeholder="Vote title..."]').first().fill("Workspace Vote Test");
    await page.locator('[placeholder="Option 1"]').first().fill("Option A");
    await page.locator('[placeholder="Option 2"]').first().fill("Option B");

    // Create vote
    await page.getByRole("button", { name: /create vote/i }).click();

    await expect(page.getByRole("button", { name: /close vote/i })).toBeVisible({ timeout: 10000 });
  });

  // ── 8. UI: 关闭投票 ───────────────────────────────────────────────────────

  test("8. UI: close vote — results visible", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Switch to agenda_vote to see vote controls
    await page.getByRole("button", { name: /议程与投票/i }).click();

    // Close vote
    const closeBtn = page.getByRole("button", { name: /close vote/i });
    await expect(closeBtn).toBeVisible({ timeout: 10000 });
    await closeBtn.click();

    await expect(page.getByText("Workspace Vote Test").first()).toBeVisible({ timeout: 10000 });
  });

  // ── 9. UI: 结束会议 ───────────────────────────────────────────────────────

  test("9. UI: end meeting — verify ended view, results directly visible, no workspace dependency", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Handle confirm dialog and click End Meeting
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: /结束会议/i }).click();
    await page.waitForTimeout(2000);

    // Verify ended meeting view
    await expect(page.getByText("Meeting Ended").first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("Workspace E2E").first()).toBeVisible();
    await expect(page.getByText("Workspace Vote Test").first()).toBeVisible();

    // Current Phase must NOT be visible in ended meeting view
    await expect(page.getByText("Current Phase:")).toHaveCount(0);

    // Workspace buttons still visible (use role to avoid "OVERVIEW" ambiguity with heading)
    await expect(page.getByRole("button", { name: /会议总览/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /议程与投票/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /服务与记录/i })).toBeVisible();
  });

  // ── 10. UI: 新会议 + 刷新验证默认 overview ─────────────────────────────────

  test("10. UI: new meeting, refresh, workspace defaults back to overview", async ({ page, request }) => {
    // API cleanup: ensure no leftover active meeting
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      await request.post(`${BACKEND}/api/meetings/${activeJson.data.id}/end`);
    }

    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create + start a new meeting via UI
    await page.locator('[placeholder="Meeting title"]').fill("Refresh Workspace Check");
    await page.getByRole("button", { name: /create pending meeting/i }).click();
    await page.waitForTimeout(500);

    await expect(page.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });

    await page.getByRole("button", { name: /start meeting/i }).click();

    // Wait for active meeting indicators
    await waitActiveAdmin(page);

    // Default workspace is overview — conference table visible, Current Phase not visible
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).toBeVisible();
    await expect(page.getByText("Current Phase:")).toHaveCount(0);

    // Switch to agenda_vote
    await page.getByRole("button", { name: /议程与投票/i }).click();
    await page.waitForTimeout(300);
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).not.toBeVisible();

    // Refresh the page — workspace must default back to "overview"
    await page.reload({ waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // After refresh, workspace should be overview (default)
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).toBeVisible();
    await expect(page.getByText("Current Phase:")).toHaveCount(0);
  });
});
