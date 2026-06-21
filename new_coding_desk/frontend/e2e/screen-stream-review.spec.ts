/**
 * Phase 4–5 E2E acceptance tests for screen stream feature.
 *
 * Uses page.route() to mock all backend APIs — no real Agent, FFmpeg, or MediaMTX.
 * ALL tests assert the TARGET contract.  Tests FAIL now because ScreenView
 * and HostDisplayControl are not implemented — this is CORRECT.
 *
 * No conditionals, no console.log, no skip/xfail.
 *
 * Phase 4 coverage:
 *   1. /screen page opens (data-testid="screen-view")
 *   2. iframe URL uses current hostname
 *   3. Offline state and retry
 *   4. No control buttons on /screen
 *   5. /seat/1 can navigate to /screen via "共享画面" entry
 *
 * Phase 5 coverage:
 *   6. /admin shows control buttons disabled when Agent unreachable + hint
 *   7. Agent mock reachable → PPT click POSTs to 127.0.0.1:8766
 *   8. No /api/host-display/activate request generated
 */

import { test, expect, Page } from "@playwright/test";

// ── Shared mock data ─────────────────────────────────────────────────────────

const ACTIVE_MEETING = {
  success: true, message: "OK",
  data: { id: 1, title: "E2E Screen Stream Test", status: "active", started_at: "2026-06-18T10:00:00Z" },
};

const SEATS = {
  success: true, message: "OK",
  data: Array.from({ length: 10 }, (_, i) => ({
    seat_id: i + 1, status: "vacant" as const, attendee_id: null, updated_at: "2026-06-18T00:00:00Z",
  })),
};

const EMPTY_RESPONSE = { success: true, message: "OK", data: null };
const EMPTY_ARRAY = { success: true, message: "OK", data: [] };

// NOT wrapped in {success, data} — backend returns the Pydantic model directly.
const HOST_DISPLAY_STATUS_ONLINE = {
  agent_state: "online" as const,
  stream_state: "online" as const,
  active_app: "powerpoint",
  viewer_count: null,
  apps: {
    powerpoint: { running: true, window_found: true },
    solidworks: { running: true, window_found: true },
    smartdesk: { running: true, window_found: true },
  },
  profile: { width: null, height: null, fps: null },
};

/** Regex matching only root-level /api/ paths (not e.g. /src/api/) */
const API_ROUTE = /^https?:\/\/[^/]+\/api(?:\/|$)/;

type MockAdminApiOptions = {
  hostDisplayStatus?: typeof HOST_DISPLAY_STATUS_ONLINE;
  onBackendActivate?: () => void;
};

async function mockAdminApi(page: Page, options: MockAdminApiOptions = {}) {
  const hostDisplayStatus = options.hostDisplayStatus ?? HOST_DISPLAY_STATUS_ONLINE;

  // Keep all backend API behavior in one dispatcher so Playwright's LIFO
  // route precedence cannot silently replace a more specific mock.
  await page.route(API_ROUTE, async (route) => {
    const url = route.request().url();

    if (url.includes("/api/host-display/activate")) {
      options.onBackendActivate?.();
      return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Not found" }) });
    }
    if (url.includes("/api/meetings/active"))
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ACTIVE_MEETING) });
    if (url.includes("/api/seats/speaker"))
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true, message: "OK", data: { seat_id: null } }) });
    if (url.includes("/api/seats"))
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SEATS) });
    if (url.includes("/api/votes/active"))
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EMPTY_RESPONSE) });
    if (url.includes("/api/meetings/") && url.includes("/attendees"))
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EMPTY_ARRAY) });
    if (url.includes("/api/meetings/") && url.includes("/agendas"))
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EMPTY_ARRAY) });
    if (url.includes("/api/service-calls"))
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EMPTY_ARRAY) });
    if (url.includes("/api/translations"))
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ success: true, message: "OK", data: { meeting_id: 1, entries: [] } }) });
    if (url.includes("/api/host-display/status"))
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(hostDisplayStatus) });

    // Default fallback for any unmatched API routes
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EMPTY_RESPONSE) });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// Phase 4 — /screen
// ══════════════════════════════════════════════════════════════════════════════

test.describe("Phase 4 — /screen viewing page", () => {
  test("1. /screen page opens and shows ScreenView component", async ({ page }) => {
    await mockAdminApi(page);
    await page.goto("/screen", { waitUntil: "networkidle" });

    // Target: ScreenView renders with data-testid="screen-view"
    // Will FAIL until ScreenView is implemented
    await expect(page.locator("[data-testid=\"screen-view\"]")).toBeVisible({ timeout: 5000 });
  });

  test("2. iframe URL uses current hostname", async ({ page }) => {
    await mockAdminApi(page);

    await page.goto("/screen", { waitUntil: "networkidle" });

    // Target: iframe with data-testid="stream-iframe" src = http://{hostname}:8889/screen?...
    const iframe = page.locator("[data-testid=\"stream-iframe\"]");
    await expect(iframe).toBeVisible({ timeout: 5000 });
    const src = await iframe.getAttribute("src");

    // Must use the page's own hostname exactly — not a hardcoded IP.
    expect(new URL(src!).hostname).toBe(new URL(page.url()).hostname);
  });

  test("3. offline state shown with retry button", async ({ page }) => {
    await mockAdminApi(page, {
      hostDisplayStatus: {
        agent_state: "online" as const,
        stream_state: "offline" as const,
        active_app: null,
        viewer_count: null,
        apps: {
          powerpoint: { running: false, window_found: false },
          solidworks: { running: false, window_found: false },
          smartdesk: { running: false, window_found: false },
        },
        profile: { width: null, height: null, fps: null },
      },
    });

    await page.goto("/screen", { waitUntil: "networkidle" });

    // Target: when stream_state=offline, ScreenView shows data-testid="stream-offline"
    // and a retry button data-testid="screen-retry".
    await expect(page.locator("[data-testid=\"stream-offline\"]")).toBeVisible({ timeout: 5000 });
    await expect(page.locator("[data-testid=\"screen-retry\"]")).toBeVisible();
  });

  test("4. /screen does NOT have PowerPoint, SolidWorks, or SmartDesk control buttons", async ({ page }) => {
    await mockAdminApi(page);

    await page.goto("/screen", { waitUntil: "networkidle" });

    // First confirm we're on the ScreenView page.
    await expect(page.locator("[data-testid=\"screen-view\"]")).toBeVisible({ timeout: 5000 });

    // Then verify control buttons do NOT exist on /screen.
    await expect(page.locator("[data-testid=\"activate-powerpoint\"]")).toHaveCount(0);
    await expect(page.locator("[data-testid=\"activate-solidworks\"]")).toHaveCount(0);
    await expect(page.locator("[data-testid=\"activate-smartdesk\"]")).toHaveCount(0);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// Phase 4 — /seat -> /screen navigation
// ══════════════════════════════════════════════════════════════════════════════

test.describe("Phase 4 — /seat/:seatId screen share entry", () => {
  test("5. /seat/1 provides a '共享画面' / 'Screen Share' entry linking to /screen", async ({ page }) => {
    await mockAdminApi(page);
    await page.route(/^https?:\/\/[^/]+\/api\/service-calls\/current/, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EMPTY_RESPONSE) }));

    // Mock WebSocket as connected to prevent the "Connection Lost" overlay
    // (no real backend available in the test environment).
    await page.routeWebSocket(/^ws:\/\/[^/]+\/ws\//, () => {
      /* Accept the mock connection without calling connectToServer().
       * The client-side onopen fires immediately → status stays "connected",
       * which matches the production scenario where the backend WebSocket
       * service is running.  No messages are exchanged. */
    });

    await page.goto("/seat/1", { waitUntil: "networkidle" });

    // Target: SeatTablet shows a button/link with data-testid="seat-screen-entry"
    // that navigates to /screen when clicked.
    const screenEntry = page.locator("[data-testid=\"seat-screen-entry\"]");
    await expect(screenEntry).toBeVisible({ timeout: 10000 });
    await expect(screenEntry).toContainText(/共享画面|Screen Share/i);

    await screenEntry.click();
    await page.waitForTimeout(500);

    // After clicking, the URL should be /screen
    expect(page.url()).toContain("/screen");
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// Phase 5 — /admin host display control
// ══════════════════════════════════════════════════════════════════════════════

test.describe("Phase 5 — /admin host display control", () => {
  test("6. /admin shows disabled control buttons + '仅中央主机本机可用' when Agent unreachable", async ({ page }) => {
    await mockAdminApi(page);
    // Mock WebSocket so the "Connection Lost" overlay does not block clicks.
    await page.routeWebSocket(/ws\//, () => {});

    // Make the loopback Agent unreachable
    await page.route("http://127.0.0.1:8766/status", (route) =>
      route.abort("connectionrefused"));

    await page.goto("/admin", { waitUntil: "networkidle" });

    // Target: HostDisplayControl card exists with disabled buttons and hint.
    await expect(page.locator("[data-testid=\"host-display-control\"]")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("[data-testid=\"local-agent-unreachable\"]")).toBeVisible();
    await expect(page.locator("[data-testid=\"activate-powerpoint\"]")).toBeDisabled();
    await expect(page.locator("[data-testid=\"activate-solidworks\"]")).toBeDisabled();
    await expect(page.locator("[data-testid=\"activate-smartdesk\"]")).toBeDisabled();
  });

  test("7. Agent reachable → clicking PPT POSTs to 127.0.0.1:8766 with correct body", async ({ page }) => {
    await mockAdminApi(page);
    // Mock WebSocket so the "Connection Lost" overlay does not block clicks.
    await page.routeWebSocket(/ws\//, () => {});

    // Make the loopback Agent reachable
    await page.route("http://127.0.0.1:8766/status", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok", agent_state: "online" }) }));

    // Track POSTs to activate endpoint
    const activateRequests: string[] = [];
    await page.route("http://127.0.0.1:8766/activate", (route, request) => {
      if (request.method() === "POST") {
        activateRequests.push(request.postData() ?? "");
      }
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
    });

    await page.goto("/admin", { waitUntil: "networkidle" });

    // Wait for the card and click PPT
    const pptBtn = page.locator("[data-testid=\"activate-powerpoint\"]");
    await expect(pptBtn).toBeVisible({ timeout: 10000 });
    await expect(pptBtn).toBeEnabled();
    await pptBtn.click();
    await page.waitForTimeout(500);

    // Must have posted to 127.0.0.1:8766 with the correct body
    expect(activateRequests.length).toBeGreaterThanOrEqual(1);
    const lastBody = JSON.parse(activateRequests[activateRequests.length - 1]);
    expect(lastBody).toEqual({ app: "powerpoint" });
  });

  test("8. PPT click only POSTs to loopback Agent, never to /api/host-display/activate", async ({ page }) => {
    // Count calls to both endpoints.
    const backendActivateCalls: string[] = [];
    const loopbackActivateCalls: string[] = [];

    await mockAdminApi(page, {
      onBackendActivate: () => backendActivateCalls.push("called"),
    });
    // Mock WebSocket so the "Connection Lost" overlay does not block clicks.
    await page.routeWebSocket(/ws\//, () => {});
    await page.route("http://127.0.0.1:8766/activate", (route, request) => {
      if (request.method() === "POST") {
        loopbackActivateCalls.push(request.postData() ?? "");
      }
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
    });
    await page.route("http://127.0.0.1:8766/status", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok", agent_state: "online" }) }));

    await page.goto("/admin", { waitUntil: "networkidle" });

    // First confirm the control card exists with an enabled PPT button.
    const card = page.locator("[data-testid=\"host-display-control\"]");
    await expect(card).toBeVisible({ timeout: 10000 });

    const pptBtn = card.locator("[data-testid=\"activate-powerpoint\"]");
    await expect(pptBtn).toBeEnabled();
    await pptBtn.click();
    await page.waitForTimeout(500);

    // The loopback Agent must have received the activate call.
    expect(loopbackActivateCalls.length).toBeGreaterThanOrEqual(1);

    // The backend proxy must NOT have been called.
    expect(backendActivateCalls).toHaveLength(0);
  });
});
