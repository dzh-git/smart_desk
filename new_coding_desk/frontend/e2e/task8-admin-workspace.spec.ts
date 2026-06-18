/**
 * Task 8 E2E — Admin Workspace 验收与截图检查
 *
 * 覆盖流程：
 *   1. 打开 /admin
 *   2. 创建 pending meeting
 *   3. 点击 Start Meeting
 *   4. 验证 Current Phase 不存在
 *   5. 验证三个 Workspace 按钮存在
 *   6. 默认 overview：会议桌总览可见，参会人员可见
 *   7. 切换到 agenda_vote：AgendaPanel 可见，Create Vote 可见
 *   8. 新增 agenda 并确认显示
 *   9. 创建 vote 并确认显示
 *   10. 切换到 service_records：ServicePanel 可见，TranscriptPanel 可见
 *   11. 切回 overview：会议桌和参会人恢复可见
 *   12. 结束会议
 *   13. 验证 meeting ended 结果直接可见（不依赖 Workspace）
 *   14. 刷新 /admin，Workspace 默认回到 overview
 *
 * 截图保存：
 *   - test-results/admin-workspace-overview.png
 *   - test-results/admin-workspace-agenda-vote.png
 *   - test-results/admin-workspace-service-records.png
 *   - test-results/admin-workspace-ended.png
 *
 * Prerequisites:
 *   - Backend: localhost:8000 (ENABLE_DEMO_SEAT_API=true, ENABLE_DEMO_SEED=true)
 *   - Frontend: localhost:5173 (dev server, VITE_ENABLE_DEMO_CONTROLS=true)
 */

import { test, expect } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const BACKEND = "http://127.0.0.1:8000";
const SCREENSHOT_DIR = path.resolve(__dirname, "..", "test-results");

test.describe("Task 8 — Admin Workspace full acceptance", () => {
  test.describe.configure({ mode: "serial" });

  // ── Helpers ──────────────────────────────────────────────────────────────────
  /** Wait until the admin active-meeting UI is fully loaded (workspace buttons + end meeting). */
  async function waitActiveAdmin(page: import("@playwright/test").Page) {
    // The 结束会议 / END MEETING button only appears in active meeting state
    await expect(page.getByRole("button", { name: /结束会议/i })).toBeVisible({ timeout: 20000 });
    // Three workspace buttons must also be visible
    await expect(page.getByRole("button", { name: /会议总览/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /议程与投票/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /服务与记录/i })).toBeVisible();
  }

  // ── 1. API Cleanup ──────────────────────────────────────────────────────────

  test("1. API cleanup: clear any leftover active meeting", async ({ request }) => {
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      await request.post(`${BACKEND}/api/meetings/${activeJson.data.id}/end`);
    }
    const checkResp = await request.get(`${BACKEND}/api/meetings/active`);
    const checkJson = await checkResp.json();
    expect(checkJson.data).toBeNull();
  });

  // ── 2. Create meeting + Start + Verify workspace buttons ────────────────────

  test("2. UI: create pending meeting, start, verify Current Phase removed and three workspace buttons", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });

    await expect(page.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create pending meeting
    await page.locator('[placeholder="Meeting title"]').fill("Admin Workspace E2E");
    await page.getByRole("button", { name: /create pending meeting/i }).click();
    await page.waitForTimeout(500);

    await expect(page.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });

    // Start the meeting
    await page.getByRole("button", { name: /start meeting/i }).click();

    // Wait for reliable active meeting indicators (workspace buttons + end meeting)
    await waitActiveAdmin(page);

    // Current Phase must NOT be visible (completely removed)
    await expect(page.getByText("当前阶段")).toHaveCount(0);
    await expect(page.getByText("CURRENT PHASE")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "General" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Agenda Discussion" })).toHaveCount(0);

    // Three workspace buttons must be visible
    await expect(page.getByRole("button", { name: /会议总览/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /议程与投票/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /服务与记录/i })).toBeVisible();

    // End Meeting button confirms active state
    await expect(page.getByRole("button", { name: /结束会议/i })).toBeVisible();
  });

  // ── 3. Default workspace is overview — conference table + attendees ─────────

  test("3. UI: default overview workspace shows conference table and attendees", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Conference table should be visible
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).toBeVisible();

    // Attendees section should be visible
    await expect(page.getByText("参会人员")).toBeVisible();

    // Agenda/Vote/Service/Transcript panel headings should NOT exist in overview
    // "议程控制台" is inside a PanelCard which is conditionally rendered
    await expect(page.getByText("议程控制台")).toHaveCount(0);
    await expect(page.getByText("服务请求")).toHaveCount(0);
    await expect(page.getByText("会议记录")).toHaveCount(0);

    // Take overview screenshot
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "admin-workspace-overview.png"),
      fullPage: true,
    });
  });

  // ── 4. Switch to agenda_vote workspace ──────────────────────────────────────

  test("4. UI: switch to agenda_vote shows agenda and vote panels", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Click agenda_vote button
    await page.getByRole("button", { name: /议程与投票/i }).click();

    // Conference table should NOT be visible in agenda_vote workspace
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).not.toBeVisible();

    // Attendees heading should NOT be visible in agenda_vote
    await expect(page.getByRole("heading", { name: /参会人员/i })).not.toBeVisible();

    // Agenda title input should be visible (no .catch)
    await expect(page.getByPlaceholder("输入议题标题 / TOPIC TITLE").first()).toBeVisible();

    // Create Vote form should be visible (no open vote)
    await expect(page.getByPlaceholder("Vote title...")).toBeVisible();
    await expect(page.getByPlaceholder("Option 1")).toBeVisible();
    await expect(page.getByPlaceholder("Option 2")).toBeVisible();
  });

  // ── 5. Add agenda item ─────────────────────────────────────────────────────

  test("5. UI: add new agenda item and verify display", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Switch to agenda_vote
    await page.getByRole("button", { name: /议程与投票/i }).click();

    // Add an agenda item
    await page.locator('[placeholder="输入议题标题 / TOPIC TITLE"]').first().fill("Review Budget Proposal");
    await page.getByRole("button", { name: /添加/i }).click();

    // Verify the agenda item appears
    await expect(page.getByText("Review Budget Proposal")).toBeVisible({ timeout: 10000 });
  });

  // ── 6. Create a vote ───────────────────────────────────────────────────────

  test("6. UI: create a vote and verify voting area displays", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Switch to agenda_vote
    await page.getByRole("button", { name: /议程与投票/i }).click();

    // Fill vote form
    await page.locator('[placeholder="Vote title..."]').first().fill("Budget Approval Vote");
    await page.locator('[placeholder="Option 1"]').first().fill("Approve");
    await page.locator('[placeholder="Option 2"]').first().fill("Reject");

    // Create vote
    await page.getByRole("button", { name: /create vote/i }).click();

    // Verify vote created — Close Vote button should appear
    await expect(page.getByRole("button", { name: /close vote/i })).toBeVisible({ timeout: 10000 });

    // Take agenda_vote screenshot
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "admin-workspace-agenda-vote.png"),
      fullPage: true,
    });
  });

  // ── 7. Close the vote ──────────────────────────────────────────────────────

  test("7. UI: close vote and verify results", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Switch to agenda_vote to see vote controls
    await page.getByRole("button", { name: /议程与投票/i }).click();

    // Close vote
    const closeBtn = page.getByRole("button", { name: /close vote/i });
    await expect(closeBtn).toBeVisible({ timeout: 10000 });
    await closeBtn.click();

    // Verify vote title still visible after close
    await expect(page.getByText("Budget Approval Vote").first()).toBeVisible({ timeout: 10000 });
  });

  // ── 8. Switch to service_records workspace ─────────────────────────────────

  test("8. UI: switch to service_records shows service and transcript panels", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // Click service_records button
    await page.getByRole("button", { name: /服务与记录/i }).click();
    await page.waitForTimeout(300);

    // Conference table should NOT be visible
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).not.toBeVisible();

    // Attendees heading should NOT be visible
    await expect(page.getByRole("heading", { name: /参会人员/i })).not.toBeVisible();

    // ServicePanel should be visible (Service Requests section — uses PanelCard)
    await expect(page.getByText("服务请求").first()).toBeVisible();

    // TranscriptPanel should exist (main section — uses PanelCard)
    await expect(page.getByText("会议记录").first()).toBeVisible();

    // Take service_records screenshot
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "admin-workspace-service-records.png"),
      fullPage: true,
    });
  });

  // ── 9. Switch back to overview ─────────────────────────────────────────────

  test("9. UI: switch back to overview restores conference table and attendees", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // First switch to service_records
    await page.getByRole("button", { name: /服务与记录/i }).click();
    await page.waitForTimeout(300);
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).not.toBeVisible();

    // Switch back to overview
    await page.getByRole("button", { name: /会议总览/i }).click();
    await page.waitForTimeout(300);

    // Conference table should return
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).toBeVisible();

    // Attendees should return
    await expect(page.getByText("参会人员")).toBeVisible();
  });

  // ── 10. End meeting ────────────────────────────────────────────────────────

  test("10. UI: end meeting — verify ended view with results directly visible", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // End the meeting
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: /结束会议/i }).click();
    await page.waitForTimeout(2000);

    // Verify ended meeting view
    await expect(page.getByText("Meeting Ended").first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("Admin Workspace E2E").first()).toBeVisible();

    // Vote results directly visible (not dependent on workspace switching)
    await expect(page.getByText("Budget Approval Vote").first()).toBeVisible();

    // Current Phase must NOT be visible
    await expect(page.getByText("Current Phase:")).toHaveCount(0);

    // Take ended meeting screenshot
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "admin-workspace-ended.png"),
      fullPage: true,
    });
  });

  // ── 11. Refresh — workspace defaults to overview ────────────────────────────

  test("11. UI: refresh with active meeting, workspace defaults to overview", async ({ page, request }) => {
    // API cleanup: ensure no leftover active meeting
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      await request.post(`${BACKEND}/api/meetings/${activeJson.data.id}/end`);
    }

    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create + start a new meeting
    await page.locator('[placeholder="Meeting title"]').fill("Workspace Default Check");
    await page.getByRole("button", { name: /create pending meeting/i }).click();
    await page.waitForTimeout(500);

    await expect(page.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });

    await page.getByRole("button", { name: /start meeting/i }).click();

    // Wait for active meeting indicators
    await waitActiveAdmin(page);

    // Default is overview — conference table visible
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).toBeVisible();

    // Current Phase must NOT exist
    await expect(page.getByText("Current Phase:")).toHaveCount(0);

    // Switch to agenda_vote to prove non-default
    await page.getByRole("button", { name: /议程与投票/i }).click();
    await page.waitForTimeout(300);
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).not.toBeVisible();

    // Refresh the page — workspace should default back to overview
    await page.reload({ waitUntil: "networkidle" });
    await waitActiveAdmin(page);

    // After refresh, overview should be default
    await expect(page.getByText(/Conference Room.*Seat Overview/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /议程与投票/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /服务与记录/i })).toBeVisible();

    // Current Phase must NEVER appear
    await expect(page.getByText("Current Phase:")).toHaveCount(0);
  });
});
