import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { SeatTablet } from "../components/SeatTablet";

// ── Mock isDemoControlsEnabled ───────────────────────────────────────────────
let mockDemoControls = false;

vi.mock("../components/shared", async () => {
  const actual = await vi.importActual("../components/shared");
  return {
    ...actual,
    isDemoControlsEnabled: () => mockDemoControls,
  };
});

// ── Mock WebSocket (simple, synchronous) ─────────────────────────────────────

let lastWsOnClose: (() => void) | null = null;
let lastWsOnMessage: ((ev: { data: string }) => void) | null = null;

class SimpleMockWebSocket {
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
    lastWsOnClose = () => {
      this.readyState = 3;
      if (this.onclose) this.onclose();
    };
    lastWsOnMessage = (ev) => {
      if (this.onmessage) this.onmessage(ev);
    };
    // Defer onopen to microtask so the real handler is assigned first
    Promise.resolve().then(() => {
      this.readyState = 1;
      if (this.onopen) this.onopen();
    });
  }

  close() {
    this.readyState = 3;
    lastWsOnClose = null;
    if (this.onclose) this.onclose();
  }

  send(_data: string) {}
}

function triggerWsEvent(event: string, meetingId: number, payload: Record<string, unknown> = {}) {
  if (lastWsOnMessage) {
    lastWsOnMessage({
      data: JSON.stringify({
        event,
        meeting_id: meetingId,
        timestamp: Math.floor(Date.now() / 1000),
        payload,
      }),
    });
  }
}

function wsDisconnect() {
  if (lastWsOnClose) {
    lastWsOnClose();
  }
}

beforeEach(() => {
  lastWsOnClose = null;
  lastWsOnMessage = null;
  globalThis.WebSocket = SimpleMockWebSocket as unknown as typeof WebSocket;
  mockDemoControls = false;
});

afterEach(() => {
  mockDemoControls = false;
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

/** Create a generic active meeting + seats mock factory */
function createSeatMock(seatStatus: "vacant" | "occupied_unchecked" | "checked_in" = "vacant") {
  return (url: string) => {
    if (url === "/api/meetings/active") {
      return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
    }
    if (url === "/api/seats") {
      const seats = Array.from({ length: 10 }, (_, i) => ({
        seat_id: i + 1,
        status: i === 0 ? seatStatus : ("vacant" as const),
        attendee_id: i === 0 && seatStatus === "checked_in" ? 1 : null,
        updated_at: "2026-01-01T00:00:00Z",
      }));
      return okResponse(seats);
    }
    if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
    if (url === "/api/votes/active") return okResponse(null);
    if (url.includes("/api/service-calls/current")) return okResponse(null);
    if (url === "/api/meetings/1/attendees") {
      if (seatStatus === "checked_in") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      return okResponse([]);
    }
    if (url === "/api/meetings/1/agendas") return okResponse([]);
    if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
    return okResponse(null);
  };
}

beforeEach(() => {
  mockFetch.mockReset();
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("SeatTablet - loading state", () => {
  it("shows loading state initially", () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    expect(screen.getByText("Loading seat data...")).toBeInTheDocument();
  });
});

describe("SeatTablet - error state", () => {
  it("shows error state with retry button", async () => {
    mockFetch.mockRejectedValue(new Error("API failure"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Failed to load data")).toBeInTheDocument();
    });
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});

describe("SeatTablet - no meeting state", () => {
  it("shows waiting message when no active meeting", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Waiting for Meeting")).toBeInTheDocument();
    });
  });
});

describe("SeatTablet - vacant seat state", () => {
  it("shows vacant seat with waiting message and no demo controls by default", async () => {
    mockFetch.mockImplementation(createSeatMock("vacant"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Vacant/)).toBeInTheDocument();
    });
    expect(screen.getByText("Waiting for occupant")).toBeInTheDocument();
    expect(screen.queryByText("Occupy Seat (Demo)")).not.toBeInTheDocument();
  });

  it("shows occupy button when demo controls are enabled", async () => {
    mockDemoControls = true;
    mockFetch.mockImplementation(createSeatMock("vacant"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Occupy Seat (Demo)")).toBeInTheDocument();
    });
  });
});

describe("SeatTablet - occupied_unchecked state", () => {
  it("shows check-in prompt for occupied_unchecked seat", async () => {
    mockFetch.mockImplementation(createSeatMock("occupied_unchecked"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Check-in Required/)).toBeInTheDocument();
    });
    expect(screen.queryByText("Vacate (Demo)")).not.toBeInTheDocument();
  });

  it("shows vacate demo button when enabled", async () => {
    mockDemoControls = true;
    mockFetch.mockImplementation(createSeatMock("occupied_unchecked"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Vacate (Demo)")).toBeInTheDocument();
    });
  });
});

describe("SeatTablet - checked_in state", () => {
  it("shows checked-in attendee info", async () => {
    mockFetch.mockImplementation(createSeatMock("checked_in"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Checked In")).toBeInTheDocument();
    });
    expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    expect(screen.getByText("CEO")).toBeInTheDocument();
  });
});

// ── Check-in Action Tests ───────────────────────────────────────────────────

describe("SeatTablet - check-in action", () => {
  it("selects attendee and calls checkin API on confirm", async () => {
    mockDemoControls = true;
    const postedUrls: string[] = [];
    const postedBodies: unknown[] = [];

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      postedUrls.push(url);
      if (opts?.body) postedBodies.push(JSON.parse(opts.body as string));

      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1,
          status: i === 0 ? "occupied_unchecked" as const : "vacant" as const,
          attendee_id: null,
          updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          { id: 42, meeting_id: 1, name: "Charlie", title: "VP", seat_id: null, checked_in: false },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      // Mock checkin response
      if (url.includes("/checkin")) {
        return okResponse({ seat_id: 1, status: "checked_in", attendee_id: 42, updated_at: "2026-01-01T00:00:00Z" });
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Check-in Required/)).toBeInTheDocument();
    });

    // Click attendee "Charlie" and wait for re-render
    const charlieBtn = screen.getByText("Charlie").closest("button");
    expect(charlieBtn).toBeInTheDocument();
    await act(async () => { charlieBtn!.click(); await new Promise((r) => setTimeout(r, 50)); });

    // Wait for the Confirm button to become enabled (WS connection + state update)
    let confirmBtn: HTMLElement;
    await waitFor(() => {
      confirmBtn = screen.getByText("Confirm Check-in");
      if (confirmBtn.hasAttribute("disabled")) throw new Error("Button still disabled");
    });

    confirmBtn = screen.getByText("Confirm Check-in");
    await act(async () => {
      confirmBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify checkin API was called with correct body
    const checkinCall = postedUrls.find((u) => u.includes("/api/seats/1/checkin"));
    expect(checkinCall).toBeTruthy();
    const checkinBody = postedBodies.find((b: unknown) => (b as Record<string, unknown>)?.attendee_id === 42);
    expect(checkinBody).toEqual({ attendee_id: 42 });
  });
});

// ── Voting Tests ────────────────────────────────────────────────────────────

describe("SeatTablet - voting action", () => {
  function mockVoteScenario() {
    mockFetch.mockImplementation((url: string, _opts?: RequestInit) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1,
          status: i === 0 ? "checked_in" as const : "vacant" as const,
          attendee_id: i === 0 ? 1 : null,
          updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({ id: 10, meeting_id: 1, title: "Approve Budget", options: ["Yes", "No", "Abstain"], status: "open", is_anonymous: false });
      }
      if (url === "/api/votes/10/statistics") {
        return okResponse({ vote_id: 10, title: "Approve Budget", is_anonymous: false, status: "open", total_votes: 0, results: [
          { option: "Yes", count: 0, attendee_ids: [] },
          { option: "No", count: 0, attendee_ids: [] },
          { option: "Abstain", count: 0, attendee_ids: [] },
        ]});
      }
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });
  }

  it("submits a vote when option is selected and submit button is clicked", async () => {
    mockVoteScenario();

    let submitBody: unknown = null;
    let submitCalled = false;

    // Override the mock for vote submit
    const originalImpl = mockFetch.getMockImplementation();
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/votes/10/submit") {
        submitCalled = true;
        submitBody = opts?.body ? JSON.parse(opts.body as string) : null;
        return okResponse({ id: 10, meeting_id: 1, title: "Approve Budget", options: ["Yes", "No", "Abstain"], status: "open", is_anonymous: false });
      }
      if (typeof originalImpl === "function") {
        return (originalImpl as (url: string, _opts?: RequestInit) => ReturnType<typeof mockFetch>)(url, opts);
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Active Vote")).toBeInTheDocument();
    });

    // Find and click the "Yes" vote option button
    const yesButtons = screen.getAllByText("Yes").filter((el) => el.closest("button"));
    expect(yesButtons.length).toBeGreaterThanOrEqual(1);
    await act(async () => { yesButtons[0].closest("button")!.click(); await new Promise((r) => setTimeout(r, 50)); });

    // Wait for submit button to become enabled
    await waitFor(() => {
      const btn = screen.getByText("Submit Vote");
      if (btn.hasAttribute("disabled")) throw new Error("Button still disabled");
    });

    const submitBtn = screen.getByText("Submit Vote");
    await act(async () => {
      submitBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify vote was submitted
    expect(submitCalled).toBe(true);
    expect(submitBody).toEqual({ attendee_id: 1, option: "Yes" });
  });

  it("allows re-submission to update existing vote", async () => {
    let submitCount = 0;
    const submitBodies: unknown[] = [];

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1,
          status: i === 0 ? "checked_in" as const : "vacant" as const,
          attendee_id: i === 0 ? 1 : null,
          updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({ id: 10, meeting_id: 1, title: "Approve Budget", options: ["Yes", "No", "Abstain"], status: "open", is_anonymous: false });
      }
      if (url === "/api/votes/10/statistics") {
        return okResponse({ vote_id: 10, title: "Approve Budget", is_anonymous: false, status: "open", total_votes: 1, results: [
          { option: "Yes", count: 1, attendee_ids: [1] },
          { option: "No", count: 0, attendee_ids: [] },
          { option: "Abstain", count: 0, attendee_ids: [] },
        ]});
      }
      if (url === "/api/votes/10/submit") {
        submitCount++;
        const body = opts?.body ? JSON.parse(opts.body as string) : null;
        submitBodies.push(body);
        return okResponse({ id: 10, meeting_id: 1, title: "Approve Budget", options: ["Yes", "No", "Abstain"], status: "open", is_anonymous: false });
      }
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    // Wait for vote section
    await waitFor(() => {
      expect(screen.getByText("Active Vote")).toBeInTheDocument();
    });

    // First submission: select "Yes" and submit
    const firstYes = screen.getAllByText("Yes").filter((el) => el.closest("button"));
    await act(async () => { firstYes[0].closest("button")!.click(); });

    // Find submit button (it's the one with "Submit" or "Update" text inside)
    const allButtons = screen.getAllByRole("button");
    const submitBtn = allButtons.find((b) => b.textContent?.includes("Submit") || b.textContent?.includes("Update"));
    expect(submitBtn).toBeTruthy();

    await act(async () => {
      submitBtn!.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Second submission: select "No" and submit again
    const allNo = screen.getAllByText("No").filter((el) => el.closest("button"));
    await act(async () => { allNo[0].closest("button")!.click(); });

    const allButtons2 = screen.getAllByRole("button");
    const submitBtn2 = allButtons2.find((b) => b.textContent?.includes("Submit") || b.textContent?.includes("Update"));
    if (submitBtn2) {
      await act(async () => {
        submitBtn2.click();
        await new Promise((r) => setTimeout(r, 100));
      });
    }

    // Verify two submits happened with correct bodies
    expect(submitCount).toBe(2);
    expect(submitBodies[0]).toEqual({ attendee_id: 1, option: "Yes" });
    expect(submitBodies[1]).toEqual({ attendee_id: 1, option: "No" });
  });
});

// ── Service Call Tests ──────────────────────────────────────────────────────

describe("SeatTablet - service call actions", () => {
  it("creates a service call when a service button is clicked", async () => {
    let postToServiceCalls = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1,
          status: i === 0 ? "checked_in" as const : "vacant" as const,
          attendee_id: i === 0 ? 1 : null,
          updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/service-calls?meeting_id=1") && opts?.method === "POST") {
        postToServiceCalls = true;
        return okResponse({ id: 100, meeting_id: 1, seat_id: 1, service_type: "coffee", status: "pending", created_at: "2026-01-01T10:05:00Z" });
      }
      if (url.includes("/api/service-calls?meeting_id=1")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Service Request")).toBeInTheDocument();
    });

    // Click "Coffee" button
    const coffeeBtn = screen.getByText("Coffee").closest("button");
    expect(coffeeBtn).toBeInTheDocument();

    await act(async () => {
      coffeeBtn!.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify POST to service-calls
    expect(postToServiceCalls).toBe(true);
  });

  it("cancels a pending service call", async () => {
    let cancelCalled = false;

    mockFetch.mockImplementation((url: string, _opts?: RequestInit) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1,
          status: i === 0 ? "checked_in" as const : "vacant" as const,
          attendee_id: i === 0 ? 1 : null,
          updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) {
        return okResponse({ id: 99, meeting_id: 1, seat_id: 1, service_type: "coffee", status: "pending", created_at: "2026-01-01T10:05:00Z" });
      }
      if (url.includes("/api/service-calls/99/cancel")) {
        cancelCalled = true;
        return okResponse({ id: 99, meeting_id: 1, seat_id: 1, service_type: "coffee", status: "cancelled", created_at: "2026-01-01T10:05:00Z" });
      }
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Pending/)).toBeInTheDocument();
    });

    // Click Cancel
    const cancelBtn = screen.getByText("Cancel");
    expect(cancelBtn).toBeInTheDocument();

    await act(async () => {
      cancelBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify cancel API was called
    expect(cancelCalled).toBe(true);
  });
});

// ── checkin_prompt Event Tests ──────────────────────────────────────────────

describe("SeatTablet - checkin_prompt event", () => {
  it("triggers data refresh on checkin_prompt event for this seat", async () => {
    let fetchCount = 0;

    mockFetch.mockImplementation((url: string) => {
      fetchCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1,
          status: i === 0 ? "occupied_unchecked" as const : "vacant" as const,
          attendee_id: null,
          updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 42, meeting_id: 1, name: "Charlie", title: "VP", seat_id: null, checked_in: false }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={3} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Seat 3")).toBeInTheDocument();
    });

    const initialFetches = fetchCount;

    // Simulate checkin_prompt for seat 3 (this seat)
    await act(async () => {
      triggerWsEvent("checkin_prompt", 1, { seat_id: 3 });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Should have triggered additional fetches
    expect(fetchCount).toBeGreaterThan(initialFetches);
  });
});

// ── WebSocket Disconnect Tests ──────────────────────────────────────────────

describe("SeatTablet - WebSocket disconnect", () => {
  it("shows disconnected overlay when WS disconnects", async () => {
    mockFetch.mockImplementation(createSeatMock("vacant"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Vacant/)).toBeInTheDocument();
    });

    // Disconnect WS synchronously
    act(() => { wsDisconnect(); });

    await waitFor(() => {
      expect(screen.getByText("Connection Lost")).toBeInTheDocument();
    });
  });

  it("disables write buttons when disconnected", async () => {
    mockDemoControls = true;
    mockFetch.mockImplementation(createSeatMock("vacant"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Occupy Seat (Demo)")).toBeInTheDocument();
    });

    // Disconnect WS synchronously
    act(() => { wsDisconnect(); });

    await waitFor(() => {
      expect(screen.getByText("Connection Lost")).toBeInTheDocument();
    });

    const occupyBtn = screen.getByText("Occupy Seat (Demo)");
    expect(occupyBtn).toBeDisabled();
  });
});

// ── Voice Placeholder Tests ─────────────────────────────────────────────────

describe("SeatTablet - voice placeholder", () => {
  it("shows voice recognition placeholder without fake mic behavior", async () => {
    mockFetch.mockImplementation(createSeatMock("vacant"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Voice Recognition/)).toBeInTheDocument();
    });

    expect(screen.getByText(/语音识别接口预留/)).toBeInTheDocument();
  });
});

// ── Data Fetching Tests ─────────────────────────────────────────────────────

describe("SeatTablet - data fetching", () => {
  it("fetches seat-specific current service call for the correct seat", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1,
          status: "vacant" as const,
          attendee_id: null,
          updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) {
        expect(url).toContain("seat_id=3");
        return okResponse(null);
      }
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={3} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Seat 3")).toBeInTheDocument();
    });
  });
});
