/**
 * Phase 5 acceptance tests — central-host local /admin control card.
 *
 * ALL tests assert the TARGET contract.  Tests FAIL now because
 * HostDisplayControl is not implemented — this is CORRECT and documents
 * production gaps.  They turn green once ZCode implements the feature.
 *
 * No conditionals, no console.log, no empty pass, no skip/xfail.
 *
 * Test areas:
 *   A. Host display control card exists in /admin
 *   B. Card shows stream state, agent state, active app, window states
 *   C. Fetches GET /api/host-display/status for read-only state
 *   D. Probes http://127.0.0.1:8766/status separately for local-host detection
 *   E. Button enable/disable based on loopback agent reachability
 *   F. Activate POST goes directly to 127.0.0.1:8766, not backend proxy
 *   G. Error handling (409, 503, CORS, network) without affecting other modules
 *   H. No change to existing workspace/meeting/agenda/vote/service/speech logic
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { AdminDashboard } from "../components/AdminDashboard";

// ── Mock isDemoControlsEnabled ───────────────────────────────────────────────
const mockDemoControls = false;

vi.mock("../components/shared", async () => {
  const actual = await vi.importActual("../components/shared");
  return {
    ...actual,
    isDemoControlsEnabled: () => mockDemoControls,
  };
});

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

// ── Mock fetch ──────────────────────────────────────────────────────────────
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function okResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, message: "OK", data }),
  };
}

/** Like okResponse but does NOT wrap in {success, data} envelope.
 *  Use for endpoints whose FastAPI handler returns a Pydantic model
 *  directly (e.g. GET /api/host-display/status). */
function rawOkResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => data,
  };
}

beforeEach(() => {
  globalThis.fetch = mockFetch;
  mockFetch.mockReset();
});

// ── Admin active meeting mock factory ────────────────────────────────────────
function mockAdminActiveMeeting(agentOnline?: () => boolean) {
  mockFetch.mockImplementation((fetchUrl: string) => {
    if (fetchUrl === "/api/meetings/active") {
      return okResponse({
        id: 1, title: "Board Meeting", status: "active",
        started_at: "2026-01-01T10:00:00Z",
      });
    }
    if (fetchUrl === "/api/seats") {
      return okResponse(
        Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1, status: "vacant" as const,
          attendee_id: null, updated_at: "2026-01-01T00:00:00Z",
        })),
      );
    }
    if (fetchUrl === "/api/seats/speaker") return okResponse({ seat_id: null });
    if (fetchUrl === "/api/votes/active") return okResponse(null);
    if (fetchUrl === "/api/meetings/1/attendees") return okResponse([]);
    if (fetchUrl === "/api/meetings/1/agendas") return okResponse([]);
    if (fetchUrl === "/api/service-calls?meeting_id=1") return okResponse([]);
    if (fetchUrl === "/api/translations?meeting_id=1")
      return okResponse({ meeting_id: 1, entries: [] });
    if (fetchUrl === "http://127.0.0.1:8766/status" && agentOnline) {
      return rawOkResponse({ agent_state: agentOnline() ? "online" : "offline" });
    }
    // NOT wrapped in {success, data} — backend returns Pydantic model directly.
    if (fetchUrl === "/api/host-display/status") {
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
      });
    }
    return okResponse(null);
  });
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("Phase 5 — host display control card in /admin", () => {
  it("checks again for the Display Agent when the More menu is reopened", async () => {
    let online = false;
    mockAdminActiveMeeting(() => online);
    render(<AdminDashboard />);

    await screen.findByText("Board Meeting");
    const more = screen.getByLabelText("更多会议操作 / More meeting actions");
    fireEvent.click(more);
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("http://127.0.0.1:8766/status", expect.anything());
    });
    expect(screen.getByTestId("activate-powerpoint")).toBeDisabled();

    fireEvent.click(more);
    online = true;
    fireEvent.click(more);

    await waitFor(() => expect(screen.getByTestId("activate-powerpoint")).toBeEnabled());
  });

  it("Admin dashboard shows a '中央大屏控制' / 'Host Display' card", async () => {
    // Target: AdminDashboard includes HostDisplayControl with
    // data-testid="host-display-control".
    mockAdminActiveMeeting();

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    expect(screen.getByTestId("host-display-control")).toBeInTheDocument();
  });

  it("control card displays stream_state from GET /api/host-display/status", async () => {
    // The card maps protocol state to a bilingual user-facing label via
    // data-testid="display-stream-state".
    mockAdminActiveMeeting();

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Wait for the raw-json status fetch to resolve (async, uses apiGetRaw)
    await waitFor(() => {
      expect(screen.getByTestId("display-stream-state")).toHaveTextContent(
        /推流正常.*STREAM ONLINE/,
      );
    });
  });

  it("control card displays agent_state, active_app, and three window states", async () => {
    // Target: the card shows agent state, active app, and each app's
    // running/window_found status — identified by testids:
    //   display-agent-state, display-active-app,
    //   app-powerpoint, app-solidworks, app-smartdesk
    mockAdminActiveMeeting();

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Agent state
    expect(screen.getByTestId("display-agent-state")).toBeInTheDocument();
    // Active app
    expect(screen.getByTestId("display-active-app")).toBeInTheDocument();
    // Three app window states
    expect(screen.getByTestId("app-powerpoint")).toBeInTheDocument();
    expect(screen.getByTestId("app-solidworks")).toBeInTheDocument();
    expect(screen.getByTestId("app-smartdesk")).toBeInTheDocument();
  });
});

describe("Seat 1 tablet display relay", () => {
  it("uses the authenticated backend relay and never probes tablet loopback", async () => {
    mockAdminActiveMeeting();
    const baseImplementation = mockFetch.getMockImplementation();
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url === "/api/host-display/activate") {
        return okResponse({ app: "powerpoint", activated: true });
      }
      return baseImplementation?.(url, options);
    });

    render(
      <AdminDashboard
        hostTabletAccess={{ deviceId: "tablet-seat-01", token: "secret-token" }}
      />,
    );

    const button = await screen.findByTestId("activate-powerpoint");
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/host-display/activate",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "X-SmartDesk-Device-Token": "secret-token",
          }),
        }),
      );
    });
    expect(mockFetch).not.toHaveBeenCalledWith(
      "http://127.0.0.1:8766/status",
      expect.anything(),
    );
  });
});

describe("Phase 5 — local-host detection boundary", () => {
  it("Admin probes http://127.0.0.1:8766/status for agent reachability", async () => {
    // Target: HostDisplayControl makes a fetch to http://127.0.0.1:8766/status
    // to determine if the current browser is on the central host.
    // This is a DIRECT fetch — NOT through the backend proxy.

    let loopbackProbed = false;
    const originalFetch = globalThis.fetch;

    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "http://127.0.0.1:8766/status") {
        loopbackProbed = true;
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      return originalFetch(url, opts);
    });

    mockAdminActiveMeeting();

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Wait a moment for the probe effect to fire
    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });

    expect(loopbackProbed).toBe(true);

    globalThis.fetch = originalFetch;
  });

  it("control buttons are disabled when 127.0.0.1:8766 agent is unreachable + shows hint", async () => {
    // Target: when the local agent probe fails (connection refused), the
    // three activate buttons are disabled and a "仅中央主机本机可用" message
    // (data-testid="local-agent-unreachable") is shown.

    // Make the loopback agent probe fail
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === "http://127.0.0.1:8766/status") {
        return Promise.reject(new TypeError("Connection refused"));
      }
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url === "/api/service-calls?meeting_id=1") return okResponse([]);
      if (url === "/api/translations?meeting_id=1")
        return okResponse({ meeting_id: 1, entries: [] });
      if (url === "/api/host-display/status") {
        return rawOkResponse({
          agent_state: "online", stream_state: "online", active_app: "powerpoint",
          viewer_count: null,
          apps: {
            powerpoint: { running: true, window_found: true },
            solidworks: { running: true, window_found: true },
            smartdesk: { running: true, window_found: true },
          },
          profile: { width: null, height: null, fps: null },
        });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Unreachable hint must be shown
    expect(screen.getByTestId("local-agent-unreachable")).toBeInTheDocument();

    // All three buttons must be disabled
    const pptBtn = screen.getByTestId("activate-powerpoint");
    const swBtn = screen.getByTestId("activate-solidworks");
    const sdBtn = screen.getByTestId("activate-smartdesk");
    expect(pptBtn).toBeDisabled();
    expect(swBtn).toBeDisabled();
    expect(sdBtn).toBeDisabled();
  });

  it("control buttons are enabled when 127.0.0.1:8766 agent is reachable", async () => {
    // Target: when the local agent probe succeeds, all three buttons are enabled.
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === "http://127.0.0.1:8766/status") {
        return rawOkResponse({ status: "ok", agent_state: "online" });
      }
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url === "/api/service-calls?meeting_id=1") return okResponse([]);
      if (url === "/api/translations?meeting_id=1")
        return okResponse({ meeting_id: 1, entries: [] });
      if (url === "/api/host-display/status") {
        return rawOkResponse({
          agent_state: "online", stream_state: "online", active_app: "powerpoint",
          viewer_count: null,
          apps: {
            powerpoint: { running: true, window_found: true },
            solidworks: { running: true, window_found: true },
            smartdesk: { running: true, window_found: true },
          },
          profile: { width: null, height: null, fps: null },
        });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Wait for the async loopback probe to resolve (microtask delay).
    await waitFor(() => {
      expect(screen.getByTestId("activate-powerpoint")).toBeEnabled();
    });
    expect(screen.getByTestId("activate-solidworks")).toBeEnabled();
    expect(screen.getByTestId("activate-smartdesk")).toBeEnabled();
  });

  it("does NOT use window.location.hostname to guess whether current machine is central host", async () => {
    // Target: even when hostname is a LAN IP, the Admin still probes
    // 127.0.0.1:8766 (which fails because loopback points to the remote
    // browser's own machine).  The decision must be based on actual
    // loopback reachability, not hostname heuristics.
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "192.168.1.50" },
      writable: true,
    });

    mockAdminActiveMeeting();

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // The card MUST still exist (it shows state regardless of hostname).
    // The loopback probe to 127.0.0.1:8766 on a remote host will fail
    // (because 127.0.0.1 points to the remote machine itself), so buttons
    // must be disabled and the unreachable hint shown.
    // If the implementation used hostname heuristics instead, it would
    // falsely enable buttons when hostname is NOT localhost — that would
    // make this assertion fail.
    expect(screen.getByTestId("host-display-control")).toBeInTheDocument();
    expect(screen.getByTestId("local-agent-unreachable")).toBeInTheDocument();
    expect(screen.getByTestId("activate-powerpoint")).toBeDisabled();
    expect(screen.getByTestId("activate-solidworks")).toBeDisabled();
    expect(screen.getByTestId("activate-smartdesk")).toBeDisabled();
  });

  it("real Agent /status schema (agent_state=online, apps, active_app) enables buttons", async () => {
    // Target: the real Agent returns {"status":"ok","agent_state":"online",
    // "active_app":null,"apps":{"powerpoint":{...},...}} — no envelope.
    // The component must recognise agent_state=online as reachable.
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url === "http://127.0.0.1:8766/status") {
        return rawOkResponse({
          status: "ok",
          agent_state: "online",
          active_app: null,
          apps: {
            powerpoint: { running: false, window_found: false },
            solidworks: { running: false, window_found: false },
            smartdesk: { running: false, window_found: false },
          },
        });
      }
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url === "/api/service-calls?meeting_id=1") return okResponse([]);
      if (url === "/api/translations?meeting_id=1")
        return okResponse({ meeting_id: 1, entries: [] });
      if (url === "/api/host-display/status") {
        return rawOkResponse({
          agent_state: "online", stream_state: "online", active_app: null,
          viewer_count: null,
          apps: {
            powerpoint: { running: false, window_found: false },
            solidworks: { running: false, window_found: false },
            smartdesk: { running: false, window_found: false },
          },
          profile: { width: null, height: null, fps: null },
        });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByTestId("activate-powerpoint")).toBeEnabled();
    });
    expect(screen.getByTestId("activate-solidworks")).toBeEnabled();
    expect(screen.getByTestId("activate-smartdesk")).toBeEnabled();
  });
});

describe("Phase 5 — activation requests", () => {
  it("clicking PowerPoint button POSTs to http://127.0.0.1:8766/activate with {\"app\":\"powerpoint\"}", async () => {
    // Target: clicking the activate-powerpoint button sends a POST to
    // http://127.0.0.1:8766/activate with body {"app":"powerpoint"}.
    // It must NOT go through /api/host-display/activate.

    const activateUrls: string[] = [];
    const activateBodies: unknown[] = [];

    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "http://127.0.0.1:8766/activate" && opts?.method === "POST") {
        activateUrls.push(url);
        activateBodies.push(opts.body ? JSON.parse(opts.body as string) : null);
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "http://127.0.0.1:8766/status") {
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "/api/meetings/active") {
        return Promise.resolve(okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        }));
      }
      if (url === "/api/seats") return Promise.resolve(okResponse([]));
      if (url === "/api/seats/speaker") return Promise.resolve(okResponse({ seat_id: null }));
      if (url === "/api/votes/active") return Promise.resolve(okResponse(null));
      if (url === "/api/meetings/1/attendees") return Promise.resolve(okResponse([]));
      if (url === "/api/meetings/1/agendas") return Promise.resolve(okResponse([]));
      if (url === "/api/service-calls?meeting_id=1") return Promise.resolve(okResponse([]));
      if (url === "/api/translations?meeting_id=1")
        return Promise.resolve(okResponse({ meeting_id: 1, entries: [] }));
      if (url === "/api/host-display/status") {
        return Promise.resolve(okResponse({
          agent_state: "online", stream_state: "online", active_app: "powerpoint",
          viewer_count: null,
          apps: {
            powerpoint: { running: true, window_found: true },
            solidworks: { running: true, window_found: true },
            smartdesk: { running: true, window_found: true },
          },
          profile: { width: null, height: null, fps: null },
        }));
      }
      return Promise.resolve(okResponse(null));
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Wait for probe to resolve, then click PPT
    await waitFor(() => {
      expect(screen.getByTestId("activate-powerpoint")).toBeEnabled();
    });
    await act(async () => {
      screen.getByTestId("activate-powerpoint").click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Must post to 127.0.0.1:8766/activate
    expect(activateUrls.length).toBeGreaterThanOrEqual(1);
    expect(activateUrls[0]).toContain("127.0.0.1:8766/activate");
    expect(activateBodies[0]).toEqual({ app: "powerpoint" });
  });

  it("clicking SolidWorks button POSTs to http://127.0.0.1:8766/activate with {\"app\":\"solidworks\"}", async () => {
    const activateBodies: unknown[] = [];

    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if ((url === "http://127.0.0.1:8766/activate" || url === "http://127.0.0.1:8766/activate") && opts?.method === "POST") {
        activateBodies.push(opts.body ? JSON.parse(opts.body as string) : null);
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "http://127.0.0.1:8766/status") {
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "/api/meetings/active") {
        return Promise.resolve(okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        }));
      }
      if (url === "/api/seats") return Promise.resolve(okResponse([]));
      if (url === "/api/seats/speaker") return Promise.resolve(okResponse({ seat_id: null }));
      if (url === "/api/votes/active") return Promise.resolve(okResponse(null));
      if (url === "/api/meetings/1/attendees") return Promise.resolve(okResponse([]));
      if (url === "/api/meetings/1/agendas") return Promise.resolve(okResponse([]));
      if (url === "/api/service-calls?meeting_id=1") return Promise.resolve(okResponse([]));
      if (url === "/api/translations?meeting_id=1")
        return Promise.resolve(okResponse({ meeting_id: 1, entries: [] }));
      if (url === "/api/host-display/status") {
        return Promise.resolve(okResponse({
          agent_state: "online", stream_state: "online", active_app: "powerpoint",
          viewer_count: null,
          apps: {
            powerpoint: { running: true, window_found: true },
            solidworks: { running: true, window_found: true },
            smartdesk: { running: true, window_found: true },
          },
          profile: { width: null, height: null, fps: null },
        }));
      }
      return Promise.resolve(okResponse(null));
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    const swBtn = screen.getByTestId("activate-solidworks");
    await act(async () => {
      swBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(activateBodies[activateBodies.length - 1]).toEqual({ app: "solidworks" });
  });

  it("clicking SmartDesk button POSTs to http://127.0.0.1:8766/activate with {\"app\":\"smartdesk\"}", async () => {
    const activateBodies: unknown[] = [];

    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if ((url === "http://127.0.0.1:8766/activate" || url === "http://127.0.0.1:8766/activate") && opts?.method === "POST") {
        activateBodies.push(opts.body ? JSON.parse(opts.body as string) : null);
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "http://127.0.0.1:8766/status") {
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "/api/meetings/active") {
        return Promise.resolve(okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        }));
      }
      if (url === "/api/seats") return Promise.resolve(okResponse([]));
      if (url === "/api/seats/speaker") return Promise.resolve(okResponse({ seat_id: null }));
      if (url === "/api/votes/active") return Promise.resolve(okResponse(null));
      if (url === "/api/meetings/1/attendees") return Promise.resolve(okResponse([]));
      if (url === "/api/meetings/1/agendas") return Promise.resolve(okResponse([]));
      if (url === "/api/service-calls?meeting_id=1") return Promise.resolve(okResponse([]));
      if (url === "/api/translations?meeting_id=1")
        return Promise.resolve(okResponse({ meeting_id: 1, entries: [] }));
      if (url === "/api/host-display/status") {
        return Promise.resolve(okResponse({
          agent_state: "online", stream_state: "online", active_app: "powerpoint",
          viewer_count: null,
          apps: {
            powerpoint: { running: true, window_found: true },
            solidworks: { running: true, window_found: true },
            smartdesk: { running: true, window_found: true },
          },
          profile: { width: null, height: null, fps: null },
        }));
      }
      return Promise.resolve(okResponse(null));
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    const sdBtn = screen.getByTestId("activate-smartdesk");
    await act(async () => {
      sdBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(activateBodies[activateBodies.length - 1]).toEqual({ app: "smartdesk" });
  });

  it("does NOT call /api/host-display/activate", async () => {
    // Target: all activation goes DIRECTLY to the loopback Agent,
    // never through the backend proxy.
    // This test MUST click a button to verify the routing — if the card
    // doesn't exist, the test fails immediately (card not found).
    const backendActivateCalls: string[] = [];
    const loopbackActivateCalls: string[] = [];

    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "http://127.0.0.1:8766/activate" && opts?.method === "POST") {
        loopbackActivateCalls.push(opts.body ? JSON.parse(opts.body as string) : null);
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "/api/host-display/activate") {
        backendActivateCalls.push("called");
        return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: "Not found" }) });
      }
      if (url === "http://127.0.0.1:8766/status") {
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "/api/meetings/active") {
        return Promise.resolve(okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        }));
      }
      if (url === "/api/seats") return Promise.resolve(okResponse([]));
      if (url === "/api/seats/speaker") return Promise.resolve(okResponse({ seat_id: null }));
      if (url === "/api/votes/active") return Promise.resolve(okResponse(null));
      if (url === "/api/meetings/1/attendees") return Promise.resolve(okResponse([]));
      if (url === "/api/meetings/1/agendas") return Promise.resolve(okResponse([]));
      if (url === "/api/service-calls?meeting_id=1") return Promise.resolve(okResponse([]));
      if (url === "/api/translations?meeting_id=1")
        return Promise.resolve(okResponse({ meeting_id: 1, entries: [] }));
      if (url === "/api/host-display/status") {
        return Promise.resolve(okResponse({
          agent_state: "online", stream_state: "online", active_app: "powerpoint",
          viewer_count: null,
          apps: {
            powerpoint: { running: true, window_found: true },
            solidworks: { running: true, window_found: true },
            smartdesk: { running: true, window_found: true },
          },
          profile: { width: null, height: null, fps: null },
        }));
      }
      return Promise.resolve(okResponse(null));
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Assert the card and PPT button exist, then click it.
    const card = screen.getByTestId("host-display-control");
    expect(card).toBeInTheDocument();

    const pptBtn = screen.getByTestId("activate-powerpoint");
    expect(pptBtn).toBeEnabled();

    await act(async () => {
      pptBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // The loopback Agent must have received the activate POST.
    expect(loopbackActivateCalls.length).toBeGreaterThanOrEqual(1);
    expect(loopbackActivateCalls[0]).toEqual({ app: "powerpoint" });

    // The backend proxy must NOT have been called.
    expect(backendActivateCalls).toHaveLength(0);
  });

  it("error responses (409, 503, CORS, network) display stable error messages", async () => {
    // Target: when activation fails with 409/503/CORS/network, a visible
    // error message appears (data-testid="activate-error") without crashing.

    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "http://127.0.0.1:8766/activate" && opts?.method === "POST") {
        return Promise.resolve({
          ok: false, status: 409, statusText: "Conflict",
          json: async () => ({ detail: "App already active" }),
        });
      }
      if (url === "http://127.0.0.1:8766/status") {
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "/api/meetings/active") {
        return Promise.resolve(okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        }));
      }
      if (url === "/api/seats") return Promise.resolve(okResponse([]));
      if (url === "/api/seats/speaker") return Promise.resolve(okResponse({ seat_id: null }));
      if (url === "/api/votes/active") return Promise.resolve(okResponse(null));
      if (url === "/api/meetings/1/attendees") return Promise.resolve(okResponse([]));
      if (url === "/api/meetings/1/agendas") return Promise.resolve(okResponse([]));
      if (url === "/api/service-calls?meeting_id=1") return Promise.resolve(okResponse([]));
      if (url === "/api/translations?meeting_id=1")
        return Promise.resolve(okResponse({ meeting_id: 1, entries: [] }));
      if (url === "/api/host-display/status") {
        return Promise.resolve(okResponse({
          agent_state: "online", stream_state: "online", active_app: "smartdesk",
          viewer_count: null,
          apps: {
            powerpoint: { running: true, window_found: true },
            solidworks: { running: true, window_found: true },
            smartdesk: { running: true, window_found: true },
          },
          profile: { width: null, height: null, fps: null },
        }));
      }
      return Promise.resolve(okResponse(null));
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Click PPT to trigger an error
    const pptBtn = screen.getByTestId("activate-powerpoint");
    await act(async () => {
      pptBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Error message must be shown
    const errorEl = screen.getByTestId("activate-error");
    expect(errorEl).toBeInTheDocument();
    expect(errorEl.textContent).toBeTruthy();
  });

  it("error on activate does not affect other admin modules", async () => {
    // Target: after an activation error, the workspace tabs, meeting controls,
    // and other admin features remain functional.

    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "http://127.0.0.1:8766/activate" && opts?.method === "POST") {
        return Promise.resolve({
          ok: false, status: 503, statusText: "Service Unavailable",
          json: async () => ({ detail: "Agent busy" }),
        });
      }
      if (url === "http://127.0.0.1:8766/status") {
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "/api/meetings/active") {
        return Promise.resolve(okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        }));
      }
      if (url === "/api/seats") return Promise.resolve(okResponse([]));
      if (url === "/api/seats/speaker") return Promise.resolve(okResponse({ seat_id: null }));
      if (url === "/api/votes/active") return Promise.resolve(okResponse(null));
      if (url === "/api/meetings/1/attendees") return Promise.resolve(okResponse([]));
      if (url === "/api/meetings/1/agendas") return Promise.resolve(okResponse([]));
      if (url === "/api/service-calls?meeting_id=1") return Promise.resolve(okResponse([]));
      if (url === "/api/translations?meeting_id=1")
        return Promise.resolve(okResponse({ meeting_id: 1, entries: [] }));
      if (url === "/api/host-display/status") {
        return Promise.resolve(okResponse({
          agent_state: "online", stream_state: "online", active_app: "smartdesk",
          viewer_count: null,
          apps: {
            powerpoint: { running: true, window_found: true },
            solidworks: { running: true, window_found: true },
            smartdesk: { running: true, window_found: true },
          },
          profile: { width: null, height: null, fps: null },
        }));
      }
      return Promise.resolve(okResponse(null));
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    screen.getByLabelText("更多会议操作 / More meeting actions").click();
    // Trigger an error by clicking PPT
    const pptBtn = screen.getByTestId("activate-powerpoint");
    await act(async () => {
      pptBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Existing admin modules must still be present
    expect(screen.getByRole("button", { name: "会场 / Overview" })).toBeVisible();
    expect(screen.getByRole("button", { name: "议程 / Agenda" })).toBeVisible();
    expect(screen.getByRole("button", { name: "服务 / Services" })).toBeVisible();
  });

  it("HTTP 200 with {ok:false, detail} displays error message", async () => {
    // Target: when /activate returns 200 but {ok:false} in the body,
    // the component must show the error without crashing.
    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "http://127.0.0.1:8766/activate" && opts?.method === "POST") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ ok: false, detail: "App rejected due to resource conflict" }),
        });
      }
      if (url === "http://127.0.0.1:8766/status") {
        return Promise.resolve(rawOkResponse({ status: "ok", agent_state: "online" }));
      }
      if (url === "/api/meetings/active") {
        return Promise.resolve(okResponse({
          id: 1, title: "Board Meeting", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        }));
      }
      if (url === "/api/seats") return Promise.resolve(okResponse([]));
      if (url === "/api/seats/speaker") return Promise.resolve(okResponse({ seat_id: null }));
      if (url === "/api/votes/active") return Promise.resolve(okResponse(null));
      if (url === "/api/meetings/1/attendees") return Promise.resolve(okResponse([]));
      if (url === "/api/meetings/1/agendas") return Promise.resolve(okResponse([]));
      if (url === "/api/service-calls?meeting_id=1") return Promise.resolve(okResponse([]));
      if (url === "/api/translations?meeting_id=1")
        return Promise.resolve(okResponse({ meeting_id: 1, entries: [] }));
      if (url === "/api/host-display/status") {
        return Promise.resolve(rawOkResponse({
          agent_state: "online", stream_state: "online", active_app: "smartdesk",
          viewer_count: null,
          apps: {
            powerpoint: { running: true, window_found: true },
            solidworks: { running: true, window_found: true },
            smartdesk: { running: true, window_found: true },
          },
          profile: { width: null, height: null, fps: null },
        }));
      }
      return Promise.resolve(okResponse(null));
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByTestId("activate-powerpoint")).toBeEnabled();
    });
    await act(async () => {
      screen.getByTestId("activate-powerpoint").click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Must show the error from the response body
    const errorEl = screen.getByTestId("activate-error");
    expect(errorEl).toBeInTheDocument();
    expect(errorEl.textContent).toContain("resource conflict");
  });

  describe("Phase 5 — does not change existing admin logic", () => {
    it("existing workspace tabs still work (overview is default)", async () => {
      // Target: HostDisplayControl addition must not break workspace tabs.
      // These tests should PASS even before HostDisplayControl is implemented.
      // Use a clean mock that doesn't alter globalThis.fetch.
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
              seat_id: i + 1, status: "vacant" as const,
              attendee_id: null, updated_at: "2026-01-01T00:00:00Z",
            })),
          );
        }
        if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
        if (url === "/api/votes/active") return okResponse(null);
        if (url === "/api/meetings/1/attendees") return okResponse([]);
        if (url === "/api/meetings/1/agendas") return okResponse([]);
        if (url === "/api/service-calls?meeting_id=1") return okResponse([]);
        if (url === "/api/translations?meeting_id=1")
          return okResponse({ meeting_id: 1, entries: [] });
        return okResponse(null);
      });

      render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Board Meeting")).toBeInTheDocument();
      });

      // Workspace tabs exist — same as before HostDisplayControl addition.
      expect(screen.getByRole("button", { name: "会场 / Overview" })).toBeVisible();
      expect(screen.getByRole("button", { name: "议程 / Agenda" })).toBeVisible();
      expect(screen.getByRole("button", { name: "服务 / Services" })).toBeVisible();

      // Switch to agenda_vote
      await act(async () => {
        screen.getByRole("button", { name: "议程 / Agenda" }).click();
        await new Promise((r) => setTimeout(r, 50));
      });

      // Agenda section visible
      expect(screen.getByText(/NO ACTIVE TOPIC/)).toBeInTheDocument();
    });

    it("existing meeting controls still work", async () => {
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
              seat_id: i + 1, status: "vacant" as const,
              attendee_id: null, updated_at: "2026-01-01T00:00:00Z",
            })),
          );
        }
        if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
        if (url === "/api/votes/active") return okResponse(null);
        if (url === "/api/meetings/1/attendees") return okResponse([]);
        if (url === "/api/meetings/1/agendas") return okResponse([]);
        if (url === "/api/service-calls?meeting_id=1") return okResponse([]);
        if (url === "/api/translations?meeting_id=1")
          return okResponse({ meeting_id: 1, entries: [] });
        return okResponse(null);
      });

      render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText("Board Meeting")).toBeInTheDocument();
      });

      // Meeting control sections exist.
      expect(screen.getByRole("button", { name: /End Meeting/i, hidden: true })).not.toBeVisible();
      screen.getByLabelText("更多会议操作 / More meeting actions").click();
      expect(screen.getByRole("button", { name: /End Meeting/i })).toBeVisible();
    });
  });
});
