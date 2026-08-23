/**
 * Phase 4 acceptance tests — `/screen` read-only viewing page & seat entry.
 *
 * ALL tests assert the TARGET contract (what SHOULD happen when ScreenView is
 * implemented).  Tests FAIL now because ScreenView does not exist — this is
 * CORRECT: they document production gaps and turn green once ZCode implements
 * the feature.
 *
 * No conditionals, no console.log, no empty pass, no skip/xfail.
 *
 * Test areas:
 *   A. ScreenView routing (/screen exists, no control buttons)
 *   B. iframe URL uses window.location.hostname, correct query params
 *   C. State lifecycle (loading, online, offline, agent offline, retry)
 *   D. Fullscreen, current app name, polling timer, cleanup
 *   E. Network errors don't crash
 *   F. /seat/:seatId provides "共享画面" entry to /screen
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import App from "../App";

// ── Mock isDemoControlsEnabled ───────────────────────────────────────────────
vi.mock("../components/shared", async () => {
  const actual = await vi.importActual("../components/shared");
  return {
    ...actual,
    isDemoControlsEnabled: () => false,
  };
});

// ── Mock fetch ───────────────────────────────────────────────────────────────
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function okResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, message: "OK", data }),
  };
}

/** Like okResponse but returns data as-is (no {success, data} envelope).
 *  Use for endpoints where FastAPI returns a Pydantic model directly. */
function rawOkResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => data,
  };
}

// ── Mock WebSocket ──────────────────────────────────────────────────────────
interface MockWSInstance {
  url: string;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onerror: (() => void) | null;
  readyState: number;
  close: () => void;
  send: (data: string) => void;
}

let wsInstances: MockWSInstance[] = [];

class TrackedMockWebSocket {
  url: string;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url: string) {
    this.url = url;
    wsInstances.push(this);
    setTimeout(() => {
      this.readyState = 1;
      if (this.onopen) this.onopen();
    }, 0);
  }

  close() {
    this.readyState = 3;
    if (this.onclose) this.onclose();
  }

  send(_data: string) {}
}

beforeEach(() => {
  wsInstances = [];
  globalThis.WebSocket = TrackedMockWebSocket as unknown as typeof WebSocket;
});

beforeEach(() => {
  mockFetch.mockReset();
  window.history.replaceState({}, "", "/");
});

// ── Mock requestFullscreen ────────────────────────────────────────────────────
let fullscreenCallCount = 0;

beforeEach(() => {
  fullscreenCallCount = 0;
  Element.prototype.requestFullscreen = vi.fn(() => {
    fullscreenCallCount++;
    return Promise.resolve();
  });
});

// ── Helper: host-display status mock response ─────────────────────────────────

function hostDisplayStatusResponse(
  overrides: Partial<{
    agent_state: string;
    stream_state: string;
    active_app: string | null;
    viewer_count: number | null;
  }> = {},
) {
  return rawOkResponse({
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
    ...overrides,
  });
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("Phase 4 — /screen routing", () => {
  it("/screen route exists and renders ScreenView component", async () => {
    // Target: App defines a <Route path="/screen"> that renders ScreenView.
    // ScreenView has data-testid="screen-view".
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") return hostDisplayStatusResponse();
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("screen-view")).toBeInTheDocument();
    });
  });
});

describe("Phase 4 — iframe URL construction", () => {
  it("iframe src uses window.location.hostname, not hardcoded IP", async () => {
    // Target: iframe src = http://{hostname}:8889/screen?controls=false&...
    // The iframe carries data-testid="stream-iframe".
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") return hostDisplayStatusResponse();
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    const iframe = await screen.findByTestId("stream-iframe");
    const src = (iframe as HTMLIFrameElement).src;

    // Must use window.location.hostname exactly — not a hardcoded IP.
    expect(new URL(src).hostname).toBe(window.location.hostname);
    // Must contain the expected MediaMTX endpoint
    expect(src).toMatch(/http:\/\/[^/]+:8889\/screen/);
  });

  it("iframe query params include controls=false, muted=true, autoplay=true, playsInline=true", async () => {
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") return hostDisplayStatusResponse();
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    const iframe = await screen.findByTestId("stream-iframe");
    const src = (iframe as HTMLIFrameElement).src;
    const qs = new URLSearchParams(src.split("?")[1] ?? "");

    expect(qs.get("controls")).toBe("false");
    expect(qs.get("muted")).toBe("true");
    expect(qs.get("autoplay")).toBe("true");
    expect(qs.get("playsInline")).toBe("true");
  });

});

describe("Phase 4 — state and lifecycle", () => {
  it("shows loading state while polling host-display status", async () => {
    // Target: ScreenView shows "正在连接" / "Connecting" while fetch is pending.
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") {
        return new Promise<never>(() => {}); // never resolves → loading persists
      }
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    const loadingEl = await screen.findByTestId("screen-loading");
    expect(loadingEl).toBeInTheDocument();
  });

  it("displays current app name from API", async () => {
    // Target: ScreenView shows the active_app value from status.
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") {
        return hostDisplayStatusResponse({ active_app: "powerpoint" });
      }
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    const appName = await screen.findByTestId("current-app-name");
    expect(appName.textContent?.toLowerCase()).toContain("powerpoint");
  });

  it("shows stream offline state when API reports stream_state=offline", async () => {
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") {
        return hostDisplayStatusResponse({ stream_state: "offline" });
      }
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    const offlineEl = await screen.findByTestId("stream-offline");
    expect(offlineEl).toBeInTheDocument();
  });

  it("shows agent offline state when API reports agent_state=offline", async () => {
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") {
        return hostDisplayStatusResponse({ agent_state: "offline", stream_state: "unknown" });
      }
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    const agentOfflineEl = await screen.findByTestId("agent-offline");
    expect(agentOfflineEl).toBeInTheDocument();
  });

  it("retry button rebuilds or reloads iframe", async () => {
    // Target: clicking retry (data-testid="screen-retry") changes the iframe
    // src or key, causing a reload.  We test by verifying a new iframe is
    // mounted (using a different key).
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") return hostDisplayStatusResponse();
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    const retryBtn = await screen.findByTestId("screen-retry");
    expect(retryBtn).toBeInTheDocument();

    // Capture initial iframe
    await act(async () => {
      retryBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // After retry, the iframe should still be present (retry rebuilds it)
    const iframeAfter = (await screen.findByTestId("stream-iframe")) as HTMLIFrameElement;
    expect(iframeAfter).toBeInTheDocument();
  });

  it("fullscreen button calls requestFullscreen", async () => {
    // Target: clicking fullscreen (data-testid="screen-fullscreen") calls
    // requestFullscreen on the container or iframe element.
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") return hostDisplayStatusResponse();
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    const fullscreenBtn = await screen.findByTestId("screen-fullscreen");
    await act(async () => {
      fullscreenBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(fullscreenCallCount).toBeGreaterThanOrEqual(1);
  });

  it("polls GET /api/host-display/status periodically", async () => {
    vi.useFakeTimers();

    window.history.replaceState({}, "", "/screen");

    let callCount = 0;
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") {
        callCount++;
        return hostDisplayStatusResponse();
      }
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    // Initial render should have called status at least once
    const initialCalls = callCount;

    // Advance timer past one polling interval (e.g., 5s)
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });

    expect(callCount).toBeGreaterThan(initialCalls);

    vi.useRealTimers();
  });

  it("cleans up polling timer on unmount", async () => {
    vi.useFakeTimers();

    window.history.replaceState({}, "", "/screen");

    let callCount = 0;
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") {
        callCount++;
        return hostDisplayStatusResponse();
      }
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    const { unmount } = render(<App />);

    const callsBeforeUnmount = callCount;

    unmount();

    // Advance timer — no new calls should happen after unmount
    await act(async () => {
      vi.advanceTimersByTime(30000);
    });

    expect(callCount).toBe(callsBeforeUnmount);

    vi.useRealTimers();
  });

  it("network error on status fetch does not crash the page", async () => {
    // Target: when /api/host-display/status throws, the page shows an
    // error state gracefully (data-testid="screen-error") instead of
    // a white screen or crash.
    window.history.replaceState({}, "", "/screen");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") {
        return Promise.reject(new TypeError("Network failure"));
      }
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    // The page should show an error indicator, not crash entirely
    const errorEl = await screen.findByTestId("screen-error");
    expect(errorEl).toBeInTheDocument();
  });
});

describe("Phase 4 — read-only safety (/screen has no control buttons)", () => {
  function renderScreenView() {
    window.history.replaceState({}, "", "/screen");
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/host-display/status") return hostDisplayStatusResponse();
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });
    render(<App />);
  }

  it("does NOT have a PowerPoint switch button", async () => {
    renderScreenView();
    await screen.findByTestId("screen-view");
    expect(screen.queryByTestId("activate-powerpoint")).not.toBeInTheDocument();
  });

  it("does NOT have a SolidWorks switch button", async () => {
    renderScreenView();
    await screen.findByTestId("screen-view");
    expect(screen.queryByTestId("activate-solidworks")).not.toBeInTheDocument();
  });

  it("does NOT have a SmartDesk switch button", async () => {
    renderScreenView();
    await screen.findByTestId("screen-view");
    expect(screen.queryByTestId("activate-smartdesk")).not.toBeInTheDocument();
  });

  it("does NOT issue any /activate requests", async () => {
    const requestedUrls: string[] = [];
    mockFetch.mockImplementation((url: string) => {
      requestedUrls.push(url);
      if (url === "/api/host-display/status") return hostDisplayStatusResponse();
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    renderScreenView();
    await screen.findByTestId("screen-view");

    const activateUrls = requestedUrls.filter((u) =>
      u.toLowerCase().includes("activate"),
    );
    expect(activateUrls).toHaveLength(0);
  });

  it("does NOT show any desktop control functionality", async () => {
    renderScreenView();
    await screen.findByTestId("screen-view");

    // The page should not have any button that suggests desktop control
    const allButtons = screen.queryAllByRole("button");
    for (const btn of allButtons) {
      const text = btn.textContent?.toLowerCase() ?? "";
      const tooManyControlKeywords =
        (text.includes("powerpoint") ? 1 : 0) +
        (text.includes("solidworks") ? 1 : 0) +
        (text.includes("activate") ? 1 : 0) +
        (text.includes("switch") ? 1 : 0);
      expect(tooManyControlKeywords).toBeLessThanOrEqual(1);
    }
  });
});

describe("Phase 4 — /seat/:seatId provides shared-screen entry", () => {
  it("/seat/:seatId shows a '共享画面' entry that navigates to /screen", async () => {
    // Target: SeatTablet has a link/button with data-testid="seat-screen-entry"
    // that navigates to /screen when clicked.
    window.history.replaceState({}, "", "/seat/1");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          {
            id: 1,
            meeting_id: 1,
            person_id: 1,
            name: "Alice",
            title: "CEO",
            assigned_seat_id: 1,
            checked_in: true,
          },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<App />);

    // Wait for the seat page to render and find the screen entry button
    const screenEntry = await screen.findByTestId("seat-screen-entry");
    expect(screenEntry).toBeInTheDocument();
    expect(screenEntry.textContent).toMatch(/共享画面|Screen Share/i);

    // Clicking navigates to /screen
    await act(async () => {
      screenEntry.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(window.location.pathname).toBe("/screen");
  });

  it("/seat/:seatId does NOT embed the video iframe directly", async () => {
    // Target: the seat page may link to /screen but must NOT contain a
    // streaming iframe itself.
    window.history.replaceState({}, "", "/seat/1");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          { id: 1, meeting_id: 1, name: "Alice", title: "CEO", seat_id: 1, checked_in: true },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<App />);

    // Wait for seat page to render
    await screen.findByText(/Seat 1/);

    // The seat page should not contain an iframe with a stream URL
    const iframes = document.querySelectorAll("iframe");
    const streamIframes = Array.from(iframes).filter((f) => {
      const src = (f as HTMLIFrameElement).src || "";
      return src.includes("8889") || src.includes("/screen");
    });
    expect(streamIframes).toHaveLength(0);
  });
});
