/**
 * Task 2 E2E — 大屏端会议结束后保留投票结果
 *
 * 核心设计原则：
 *   - 单个 test 函数，使用 `browser` fixture 创建多页面
 *   - `/display` 在会议 active 时打开，保持 WS 连接
 *   - `/admin` 点击 "End Meeting" → `/display` 通过 WS 直接收到 `meeting_ended`
 *   - 验证 Meeting Ended 状态 + 保留投票结果 + sessionStorage 持久化
 *
 * Prerequisites:
 *   - Backend: localhost:8000 (ENABLE_DEMO_SEAT_API=true)
 *   - Frontend: localhost:5173 (dev server)
 *   - Playwright config auto-starts frontend via webServer
 */

import { test, expect } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8000";

test("Task 2 — Display ended meeting via WS end event", async ({ browser, request }) => {
  // ═══ 1. API Setup ═══════════════════════════════════════════════════════

  // End any leftover active meeting
  const activeResp = await request.get(`${BACKEND}/api/meetings/active`);
  const activeJson = await activeResp.json();
  if (activeJson.data) {
    await request.post(`${BACKEND}/api/meetings/${activeJson.data.id}/end`);
  }

  // Create + start meeting
  const createResp = await request.post(`${BACKEND}/api/meetings`, {
    data: { title: "Display E2E", description: "" },
  });
  const meetingId = (await createResp.json()).data.id;
  await request.post(`${BACKEND}/api/meetings/${meetingId}/start`);

  // Create attendee
  const attResp = await request.post(`${BACKEND}/api/meetings/${meetingId}/attendees`, {
    data: { name: "Tester", title: "QA" },
  });
  const attendeeId = (await attResp.json()).data.id;

  // Occupy + check-in seat 1
  await request.post(`${BACKEND}/api/dev/seats/1/occupy`);
  await request.post(`${BACKEND}/api/seats/1/checkin`, { data: { attendee_id: attendeeId } });

  // Create vote
  const voteResp = await request.post(`${BACKEND}/api/votes`, {
    data: { meeting_id: meetingId, title: "Floor", options: ["Wood", "Tile"], is_anonymous: false },
  });
  const voteId = (await voteResp.json()).data.id;

  // Submit ballot
  await request.post(`${BACKEND}/api/votes/${voteId}/submit`, {
    data: { attendee_id: attendeeId, option: "Wood" },
  });

  // Close vote so it's in "closed" state before meeting ends
  await request.post(`${BACKEND}/api/votes/${voteId}/close`);

  // ═══ 2. Open /display ═══════════════════════════════════════════════════

  const displayCtx = await browser.newContext();
  const displayPage = await displayCtx.newPage();
  await displayPage.goto("/display", { waitUntil: "networkidle" });

  // Verify display shows active meeting with closed vote result
  await expect(displayPage.getByText("Display E2E")).toBeVisible({ timeout: 15000 });
  await expect(displayPage.getByText("Floor")).toBeVisible({ timeout: 10000 });
  await expect(displayPage.getByText("Vote Result")).toBeVisible();
  await expect(displayPage.getByText("Wood").first()).toBeVisible();
  await expect(displayPage.getByText("Tile").first()).toBeVisible();
  await expect(displayPage.getByText("Meeting Ended")).not.toBeVisible();

  // ═══ 3. Admin: click "End Meeting" ══════════════════════════════════════

  const adminCtx = await browser.newContext();
  const adminPage = await adminCtx.newPage();
  await adminPage.goto("/", { waitUntil: "networkidle" });

  // Find and click "End Meeting" button
  adminPage.once("dialog", (d) => d.accept());
  const endBtn = adminPage.getByRole("button", { name: "End Meeting" });
  await expect(endBtn).toBeVisible({ timeout: 10000 });
  await endBtn.click();

  // Wait for WS event to propagate to display page
  await new Promise((r) => setTimeout(r, 3000));

  // ═══ 4. Verify /display has Meeting Ended + preserved results ═══════════

  await expect(displayPage.getByText("Meeting Ended")).toBeVisible({ timeout: 15000 });
  await expect(displayPage.getByText(/Results are preserved below/)).toBeVisible();

  // Vote results preserved
  await expect(displayPage.getByText("Floor").first()).toBeVisible({ timeout: 5000 });

  // No empty states
  await expect(displayPage.getByText("Waiting for Meeting")).not.toBeVisible();
  await expect(displayPage.getByText("No votes yet")).not.toBeVisible();

  // Verify endedMeetingId was saved to sessionStorage
  const endedId = await displayPage.evaluate(() =>
    window.sessionStorage.getItem("smartdesk.display.endedMeetingId")
  );
  expect(endedId).toBe(String(meetingId));

  // ═══ 5. Refresh display — results persist ═══════════════════════════════

  await displayPage.reload({ waitUntil: "networkidle" });

  await expect(displayPage.getByText("Meeting Ended")).toBeVisible({ timeout: 15000 });
  await expect(displayPage.getByText("Floor").first()).toBeVisible({ timeout: 5000 });

  // Cleanup
  await adminCtx.close();
  await displayCtx.close();
});
