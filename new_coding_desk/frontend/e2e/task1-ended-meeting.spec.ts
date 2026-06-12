/**
 * Task 1 E2E — 主持人端会议结束后保留会议结果视图
 *
 * Prerequisites:
 *   - Backend running at http://localhost:8000 with demo seed enabled
 *   - Frontend dev server at http://localhost:5173
 */

import { test, expect } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8000";
const ADMIN_URL = "http://localhost:5173/";

// ── Test ────────────────────────────────────────────────────────────────────

test.describe("Task 1 — meeting ended results view", () => {
  test.describe.configure({ mode: "serial" });

  let meetingId: number;
  let voteId: number;
  let attendeeId: number;

  test("1. API: create + start meeting, attendee, vote, submit, close", async ({ request }) => {
    // Clear any active meeting first
    const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
    const activeJson = await activeResp.json();
    if (activeJson.data) {
      await request.post(`${BACKEND}/api/meetings/${activeJson.data.id}/end`);
    }

    // Create meeting
    const createResp = await request.post(`${BACKEND}/api/meetings`, {
      data: { title: "E2E Meeting", description: "Playwright" },
    });
    const createJson = await createResp.json();
    expect(createJson.success).toBe(true);
    expect(typeof createJson.data.id).toBe("number");
    meetingId = createJson.data.id;

    // Start
    const startResp = await request.post(`${BACKEND}/api/meetings/${meetingId}/start`);
    const startJson = await startResp.json();
    expect(startJson.data.status).toBe("active");

    // Create attendee
    const attResp = await request.post(`${BACKEND}/api/meetings/${meetingId}/attendees`, {
      data: { name: "E2E Tester", title: "QA" },
    });
    const attJson = await attResp.json();
    expect(attJson.success).toBe(true);
    attendeeId = attJson.data.id;

    // Occupy + check-in seat 1
    await request.post(`${BACKEND}/api/dev/seats/1/occupy`);
    await request.post(`${BACKEND}/api/seats/1/checkin`, {
      data: { attendee_id: attendeeId },
    });

    // Create vote
    const voteResp = await request.post(`${BACKEND}/api/votes`, {
      data: {
        meeting_id: meetingId,
        title: "E2E Test Vote",
        options: ["Option A", "Option B"],
        is_anonymous: false,
      },
    });
    const voteJson = await voteResp.json();
    expect(voteJson.success).toBe(true);
    voteId = voteJson.data.id;

    // Submit ballot
    const submitResp = await request.post(`${BACKEND}/api/votes/${voteId}/submit`, {
      data: { attendee_id: attendeeId, option: "Option A" },
    });
    const submitJson = await submitResp.json();
    expect(submitJson.success).toBe(true);

    // Close vote
    const closeResp = await request.post(`${BACKEND}/api/votes/${voteId}/close`);
    const closeJson = await closeResp.json();
    expect(closeJson.data.status).toBe("closed");
  });

  test("2. Admin page shows vote results before ending", async ({ page }) => {
    await page.goto(ADMIN_URL, { waitUntil: "networkidle" });

    await expect(page.getByText("E2E Meeting")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("E2E Test Vote").first()).toBeVisible();
    await expect(page.getByText("Option A").first()).toBeVisible();
    await expect(page.getByText("Option B").first()).toBeVisible();
  });

  test("3. End meeting and verify ended view", async ({ page, request }) => {
    // End via API
    const endResp = await request.post(`${BACKEND}/api/meetings/${meetingId}/end`);
    const endJson = await endResp.json();
    expect(endJson.data.status).toBe("finished");

    // Write ended meeting data into sessionStorage (simulates what handleEndMeeting does)
    await page.goto(ADMIN_URL, { waitUntil: "domcontentloaded" });
    await page.evaluate(
      ({ id, title }) => {
        window.sessionStorage.setItem("endedMeetingId", String(id));
        window.sessionStorage.setItem("endedMeetingTitle", title);
      },
      { id: meetingId, title: "E2E Meeting" },
    );

    // Reload — useEvaluation is done, now page will pick up sessionStorage
    await page.reload({ waitUntil: "networkidle" });

    // Ended meeting view should appear
    await expect(page.getByText("Meeting Ended").first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("E2E Meeting").first()).toBeVisible();

    // Vote results still visible
    await expect(page.getByText("E2E Test Vote").first()).toBeVisible();
    await expect(page.getByText("1/1 closed")).toBeVisible();
  });

  test("4. Write operations hidden in ended meeting view", async ({ page }) => {
    await page.goto(ADMIN_URL, { waitUntil: "domcontentloaded" });
    // Ensure sessionStorage still has ended meeting data
    await page.evaluate(
      ({ id, title }) => {
        window.sessionStorage.setItem("endedMeetingId", String(id));
        window.sessionStorage.setItem("endedMeetingTitle", title);
      },
      { id: meetingId, title: "E2E Meeting" },
    );
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByText("Meeting Ended").first()).toBeVisible({ timeout: 10000 });

    await expect(page.getByText("End Meeting")).not.toBeVisible();
    await expect(page.getByText("Create Vote")).not.toBeVisible();
    await expect(page.getByText("Add Attendee")).not.toBeVisible();
    await expect(page.getByText("Add Agenda")).not.toBeVisible();
    await expect(page.getByText("Set Speaker")).not.toBeVisible();
    await expect(page.getByText("Clear Speaker")).not.toBeVisible();
    await expect(page.getByText("Resolve")).not.toBeVisible();
    await expect(page.getByText("No Active Meeting")).not.toBeVisible();
  });

  test("5. SessionStorage persists ended meeting across refresh", async ({ page }) => {
    await page.goto(ADMIN_URL, { waitUntil: "domcontentloaded" });
    await page.evaluate(
      ({ id, title }) => {
        window.sessionStorage.setItem("endedMeetingId", String(id));
        window.sessionStorage.setItem("endedMeetingTitle", title);
      },
      { id: meetingId, title: "E2E Meeting" },
    );
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByText("Meeting Ended").first()).toBeVisible({ timeout: 10000 });

    const endedId = await page.evaluate(() => window.sessionStorage.getItem("endedMeetingId"));
    expect(endedId).toBe(String(meetingId));

    // Refresh and verify persistence
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByText("Meeting Ended").first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("E2E Test Vote").first()).toBeVisible();
  });

  test("6. New Meeting button returns to No Active Meeting", async ({ page }) => {
    await page.goto(ADMIN_URL, { waitUntil: "domcontentloaded" });
    await page.evaluate(
      ({ id, title }) => {
        window.sessionStorage.setItem("endedMeetingId", String(id));
        window.sessionStorage.setItem("endedMeetingTitle", title);
      },
      { id: meetingId, title: "E2E Meeting" },
    );
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByText("Meeting Ended").first()).toBeVisible({ timeout: 10000 });

    await page.getByText("New Meeting").click();

    await expect(page.getByText("No Active Meeting").first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Create Pending Meeting")).toBeVisible();
  });
});
