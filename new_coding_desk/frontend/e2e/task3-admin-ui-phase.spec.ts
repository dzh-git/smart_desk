/**
 * Task 3 E2E — 主持人端增加最小阶段选择 UI
 *
 * 核心设计原则：
 *   - API 只用于环境清理（结束残留会议）
 *   - 所有核心用户流程通过真实 UI 点击完成
 *   - 每个测试独立导航到页面，不依赖前序测试的页面状态
 *   - 串行执行确保数据一致性
 *
 * Prerequisites:
 *   - Backend: localhost:8000 (ENABLE_DEMO_SEAT_API=true, ENABLE_DEMO_SEED=true)
 *   - Frontend: localhost:5173 (dev server, VITE_ENABLE_DEMO_CONTROLS=true)
 */

import { test, expect } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8000";

test.describe("Task 3 — Admin UI Phase Selector", () => {
  test.describe.configure({ mode: "serial" });

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

  // ── 2. UI: 创建会议 + 启动 + 验证阶段选择 ───────────────────────────────────

  test("2. UI: create pending meeting, start, verify phase selector default General", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    await expect(page.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create pending meeting
    await page.locator('[placeholder="Meeting title"]').fill("UI Phase E2E");
    await page.getByRole("button", { name: /create pending meeting/i }).click();
    await page.waitForTimeout(500);

    await expect(page.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });

    // Start the meeting
    await page.getByRole("button", { name: /start meeting/i }).click();
    await page.waitForTimeout(1500);

    // Verify active meeting
    await expect(page.getByText("UI Phase E2E").first()).toBeVisible({ timeout: 15000 });

    // Phase selector visible with default "General"
    await expect(page.getByText("Current Phase:")).toBeVisible();
    await expect(page.getByRole("button", { name: "General" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Agenda Discussion" })).toBeVisible();
    await expect(page.getByText("Agenda Discussion Mode")).not.toBeVisible();
  });

  // ── 3. UI: 切换到 Agenda Discussion ────────────────────────────────────────

  test("3. UI: switch to Agenda Discussion — shows phase indicator", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("UI Phase E2E").first()).toBeVisible({ timeout: 15000 });

    // Switch to Agenda Discussion
    await page.getByRole("button", { name: "Agenda Discussion" }).click();
    await page.waitForTimeout(500);

    await expect(page.getByText("Agenda Discussion Mode")).toBeVisible();
    await expect(page.getByText(/Agenda items are emphasised/)).toBeVisible();
  });

  // ── 4. UI: 在 agenda_discussion 下添加议程 ──────────────────────────────────

  test("4. UI: add agenda item in agenda_discussion mode", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("UI Phase E2E").first()).toBeVisible({ timeout: 15000 });

    // Switch to Agenda Discussion
    await page.getByRole("button", { name: "Agenda Discussion" }).click();
    await page.waitForTimeout(500);
    await expect(page.getByText("Agenda Discussion Mode")).toBeVisible();

    // Add agenda item
    await page.locator('[placeholder="Agenda title"]').first().fill("Discuss Budget");
    await page.getByRole("button", { name: "Add Agenda" }).click();
    await page.waitForTimeout(500);

    await expect(page.getByText("Discuss Budget")).toBeVisible({ timeout: 10000 });
  });

  // ── 5. UI: 切回 General ───────────────────────────────────────────────────

  test("5. UI: switch back to General — hides agenda indicator", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("UI Phase E2E").first()).toBeVisible({ timeout: 15000 });

    // Switch to Agenda Discussion first
    await page.getByRole("button", { name: "Agenda Discussion" }).click();
    await page.waitForTimeout(500);
    await expect(page.getByText("Agenda Discussion Mode")).toBeVisible();

    // Switch back to General
    await page.getByRole("button", { name: "General" }).click();
    await page.waitForTimeout(500);

    await expect(page.getByText("Agenda Discussion Mode")).not.toBeVisible();
  });

  // ── 6. UI: 创建投票 ───────────────────────────────────────────────────────

  test("6. UI: create vote unaffected by phase", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("UI Phase E2E").first()).toBeVisible({ timeout: 15000 });

    // Fill vote form
    await page.locator('[placeholder="Vote title..."]').first().fill("Phase Test Vote");
    await page.locator('[placeholder="Option 1"]').first().fill("Option A");
    await page.locator('[placeholder="Option 2"]').first().fill("Option B");

    // Create vote
    await page.getByRole("button", { name: /create vote/i }).click();
    await page.waitForTimeout(500);

    await expect(page.getByRole("button", { name: /close vote/i })).toBeVisible({ timeout: 10000 });
  });

  // ── 7. UI: 关闭投票 ───────────────────────────────────────────────────────

  test("7. UI: close vote — results visible", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("UI Phase E2E").first()).toBeVisible({ timeout: 15000 });

    // Close vote
    const closeBtn = page.getByRole("button", { name: /close vote/i });
    await expect(closeBtn).toBeVisible({ timeout: 10000 });
    await closeBtn.click();
    await page.waitForTimeout(500);

    await expect(page.getByText("Phase Test Vote").first()).toBeVisible({ timeout: 10000 });
  });

  // ── 8. UI: 结束会议 ───────────────────────────────────────────────────────

  test("8. UI: end meeting — verify ended view + no phase selector", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("UI Phase E2E").first()).toBeVisible({ timeout: 15000 });

    // Handle confirm dialog and click End Meeting
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: /end meeting/i }).click();
    await page.waitForTimeout(2000);

    // Verify ended meeting view
    await expect(page.getByText("Meeting Ended").first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("UI Phase E2E").first()).toBeVisible();
    await expect(page.getByText("Phase Test Vote").first()).toBeVisible();

    // Phase selector must NOT be visible in ended meeting view
    await expect(page.getByText("Current Phase:")).not.toBeVisible();
  });

  // ── 9. UI: 新会议 + 刷新验证默认 General ────────────────────────────────────

  test("9. UI: new meeting, refresh, phase defaults back to General", async ({ page, request }) => {
    // API cleanup: ensure no leftover active meeting (demo seed may have created one)
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      await request.post(`${BACKEND}/api/meetings/${activeJson.data.id}/end`);
    }

    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("No Active Meeting", { exact: true })).toBeVisible({ timeout: 15000 });

    // Create + start a new meeting via UI
    await page.locator('[placeholder="Meeting title"]').fill("Refresh Phase Check");
    await page.getByRole("button", { name: /create pending meeting/i }).click();
    await page.waitForTimeout(500);

    await expect(page.getByRole("heading", { name: "Pending Meeting" })).toBeVisible({ timeout: 10000 });

    await page.getByRole("button", { name: /start meeting/i }).click();
    await page.waitForTimeout(1500);

    // Verify new meeting active
    await expect(page.getByText("Refresh Phase Check").first()).toBeVisible({ timeout: 15000 });

    // Phase selector visible, default General
    await expect(page.getByText("Current Phase:")).toBeVisible();
    await expect(page.getByText("Agenda Discussion Mode")).not.toBeVisible();

    // Switch to Agenda Discussion
    await page.getByRole("button", { name: "Agenda Discussion" }).click();
    await page.waitForTimeout(300);
    await expect(page.getByText("Agenda Discussion Mode")).toBeVisible();

    // Refresh the page — phase must default back to "General"
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByText("Refresh Phase Check").first()).toBeVisible({ timeout: 15000 });

    await expect(page.getByText("Agenda Discussion Mode")).not.toBeVisible();
    await expect(page.getByText("Current Phase:")).toBeVisible();
  });
});
