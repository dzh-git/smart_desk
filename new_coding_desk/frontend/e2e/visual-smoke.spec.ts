/**
 * Visual Smoke Test — SmartDesk 三端截图验收
 *
 * 目的：
 *   - 快速验证 /admin, /seat/1, /display 三端页面能正常渲染
 *   - 在目标视口截图，供视觉验收参考
 *   - 不依赖后端运行（页面 loading/error/empty 状态也可验证渲染）
 *
 * Prerequisites:
 *   - Frontend dev server: localhost:5173 (auto-started by Playwright webServer)
 *   - Optional backend: localhost:8000 (for full meeting states)
 *
 * Usage:
 *   npx playwright test visual-smoke.spec.ts --config=playwright.config.ts
 */

import { test, expect } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SCREENSHOT_DIR = path.resolve(
  __dirname,
  "../../working/plan/task-visual-qa/screenshots",
);

test.describe("Visual Smoke — 三端截图验收", () => {
  // ── /admin (1920×1080) ──────────────────────────────────────────────────

  test("/admin at 1920×1080 — page renders with header", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/admin", { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForTimeout(2000);

    // Brand name or header is the key indicator for /admin
    await expect(
      page.getByText(/SmartDesk|No Active Meeting|Admin|主持人|Loading/).first(),
    ).toBeVisible({ timeout: 5000 });

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "visual-admin-1920x1080.png"),
      fullPage: false,
    });
  });

  test("/admin at 2560×1440 — wide layout check", async ({ page }) => {
    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.goto("/admin", { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForTimeout(2000);

    await expect(
      page.getByText(/SmartDesk|No Active Meeting|主持人|Loading/).first(),
    ).toBeVisible({ timeout: 5000 });

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "visual-admin-2560x1440.png"),
      fullPage: false,
    });
  });

  // ── /seat/1 (1280×800) ─────────────────────────────────────────────────

  test("/seat/1 at 1280×800 — touch layout renders", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/seat/1", { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForTimeout(2000);

    // Seat number or header is the key indicator for /seat/:id
    await expect(
      page.getByText(/座位 1|Seat 1|Waiting|Loading/).first(),
    ).toBeVisible({ timeout: 5000 });

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "visual-seat-1-1280x800.png"),
      fullPage: false,
    });
  });

  test("/seat/1 at 1920×1080 — full HD touch view", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/seat/1", { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForTimeout(2000);

    await expect(
      page.getByText(/座位 1|Seat 1|Waiting|Loading/).first(),
    ).toBeVisible({ timeout: 5000 });

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "visual-seat-1-1920x1080.png"),
      fullPage: false,
    });
  });

  test("/seat/1 at 1366×768 — common laptop resolution", async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/seat/1", { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForTimeout(2000);

    await expect(
      page.getByText(/座位 1|Seat 1|Waiting|Loading/).first(),
    ).toBeVisible({ timeout: 5000 });

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "visual-seat-1-1366x768.png"),
      fullPage: false,
    });
  });

  // ── /display (1920×1080) ───────────────────────────────────────────────

  test("/display at 1920×1080 — display renders with header", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/display", { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForTimeout(2000);

    // Display header or Refresh is the key indicator for /display
    await expect(
      page.getByText(/会议大屏|Command Display|等待|Refresh|Loading|Display/).first(),
    ).toBeVisible({ timeout: 5000 });

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "visual-display-1920x1080.png"),
      fullPage: false,
    });

    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });

  test("/display at 1366×768 — compact display has no horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/display", { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForTimeout(2000);

    await expect(
      page.getByText(/会议大屏|Command Display|等待|Refresh|Loading|Display/).first(),
    ).toBeVisible({ timeout: 5000 });

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "visual-display-1366x768.png"),
      fullPage: false,
    });

    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });

  test("/display at 3840×2160 — 4K display check", async ({ page }) => {
    await page.setViewportSize({ width: 3840, height: 2160 });
    await page.goto("/display", { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForTimeout(2000);

    await expect(
      page.getByText(/会议大屏|Command Display|等待|Refresh|Loading|Display/).first(),
    ).toBeVisible({ timeout: 5000 });

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "visual-display-3840x2160.png"),
      fullPage: false,
    });

    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });
});
