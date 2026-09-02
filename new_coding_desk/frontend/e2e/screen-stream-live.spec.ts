import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const STREAM_URL = "http://127.0.0.1:8889/screen";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const RUNTIME_DIR = path.resolve(
  HERE,
  "../../.smartdesk-runtime/screen-stream",
);
const FFMPEG_PID = path.join(RUNTIME_DIR, "ffmpeg.pid");

test("10 clients receive video and FFmpeg restarts after termination", async ({
  browser,
}) => {
  const contexts = await Promise.all(
    Array.from({ length: 10 }, () => browser.newContext()),
  );
  try {
    const pages = await Promise.all(contexts.map((context) => context.newPage()));
    await Promise.all(
      pages.map((page) =>
        page.goto(STREAM_URL, {
          waitUntil: "domcontentloaded",
          timeout: 30_000,
        }),
      ),
    );
    await Promise.all(
      pages.map(async (page) => {
        const video = page.locator("video").first();
        await expect(video).toBeVisible({ timeout: 30_000 });
        await expect
          .poll(
            () =>
              video.evaluate(
                (element: HTMLVideoElement) =>
                  element.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA,
              ),
            { timeout: 30_000 },
          )
          .toBe(true);
      }),
    );

    const oldPid = Number(fs.readFileSync(FFMPEG_PID, "utf8").trim());
    expect(Number.isInteger(oldPid) && oldPid > 0).toBe(true);
    process.kill(oldPid);
    await expect
      .poll(
        () => {
          try {
            return Number(fs.readFileSync(FFMPEG_PID, "utf8").trim());
          } catch {
            return oldPid;
          }
        },
        { timeout: 30_000 },
      )
      .not.toBe(oldPid);

    await Promise.all(
      pages.map(async (page) => {
        await page.reload({ waitUntil: "domcontentloaded" });
        const video = page.locator("video").first();
        await expect(video).toBeVisible({ timeout: 30_000 });
      }),
    );
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});
