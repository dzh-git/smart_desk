import { expect, test } from "@playwright/test";

test.skip(
  process.env.SMARTDESK_SPATIAL_E2E !== "true",
  "Requires the demo frontend and an active SmartDesk meeting seeded in a local test database.",
);

test.describe("SmartDesk spatial rendering", () => {
  test.use({ viewport: { width: 1280, height: 850 } });

  test("the real scene responds to workspace, pointer and route transitions", async ({ page }) => {
    test.setTimeout(150_000);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      localStorage.setItem("smartdesk.spatial.preferences.v1", JSON.stringify({ quality: "low", reducedMotion: false }));
    });
    await page.goto("/admin");
    const stage = page.getByTestId("spatial-stage");
    await expect(stage).toHaveAttribute("data-renderer", "webgl2", { timeout: 20_000 });
    await expect(stage).toHaveAttribute("data-mode", "room");

    const canvas = stage.locator("canvas");
    expect(await canvas.evaluate((element: HTMLCanvasElement) => {
      const gl = element.getContext("webgl2");
      return Boolean(gl && !gl.isContextLost() && element.width > 0 && element.height > 0);
    })).toBe(true);
    await canvas.evaluate((element) => { element.dataset.spatialTestIdentity = "shared"; });

    await page.getByRole("button", { name: "议程 / Agenda" }).click();
    await expect(stage).toHaveAttribute("data-mode", "agenda");
    await page.getByRole("button", { name: "服务 / Services" }).click();
    await expect(stage).toHaveAttribute("data-mode", "service");
    await page.getByRole("button", { name: /Overview/i }).click();
    await expect(stage).toHaveAttribute("data-mode", "room");
    await expect(page.getByTestId("conference-seat-9")).toBeVisible();

    await page.getByText("画质", { exact: true }).click();
    await page.getByLabel("渲染质量").selectOption("medium");
    await page.getByLabel("渲染质量").selectOption("low");
    await page.getByLabel("减少动效", { exact: true }).check();
    await page.getByText("画质", { exact: true }).click();
    await expect(stage.locator(".spatial-stage__fps")).toHaveCount(0);
    await stage.locator(".spatial-viewport").focus();
    const before = await canvas.screenshot({ scale: "css" });
    await page.keyboard.press("ArrowRight");
    const after = await canvas.screenshot({ scale: "css" });
    expect(before.equals(after)).toBe(false);

    await page.getByLabel("更多会议操作 / More meeting actions").click();
    await page.getByRole("button", { name: /Open seat 2/i }).click();
    await expect(page).toHaveURL(/\/seat\/2$/);
    await expect(stage).toHaveAttribute("data-mode", "station");
    await expect(stage.locator("canvas")).toHaveAttribute("data-spatial-test-identity", "shared");
    await expect(page.locator("canvas")).toHaveCount(1);

    const lost = await canvas.evaluate((element: HTMLCanvasElement) => {
      const context = element.getContext("webgl2")?.getExtension("WEBGL_lose_context");
      if (!context) return false;
      element.addEventListener("test-restore-webgl", () => context.restoreContext(), { once: true });
      context.loseContext();
      return true;
    });
    expect(lost).toBe(true);
    await expect(stage).toHaveAttribute("data-renderer", "fallback");
    await canvas.dispatchEvent("test-restore-webgl");
    await expect(stage).toHaveAttribute("data-renderer", "webgl2", { timeout: 20_000 });
    await expect(canvas).toHaveAttribute("data-spatial-test-identity", "shared");
    expect(errors).toEqual([]);
  });

  test("WebGL initialization failure keeps the host controls and seat map operable", async ({ page }) => {
    await page.addInitScript(() => {
      const context = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, options?: unknown) {
        if (type === "webgl2") return null;
        return Reflect.apply(context, this, [type, options]);
      } as typeof context;
    });
    await page.goto("/admin");
    await expect(page.getByTestId("spatial-stage")).toHaveAttribute("data-renderer", "fallback");
    await page.getByTestId("conference-seat-2").click();
    await expect(page.getByTestId("seat-assignment-select")).toBeVisible();
    await page.getByLabel("更多会议操作 / More meeting actions").click();
    await expect(page.getByRole("button", { name: /End Meeting/i })).toBeEnabled();
  });
});
