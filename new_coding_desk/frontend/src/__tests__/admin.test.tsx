import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { AdminDashboard } from "../components/AdminDashboard";

// ── Mock isDemoControlsEnabled ───────────────────────────────────────────────
// Default: false (no demo controls shown)
const mockDemoControls = false;

vi.mock("../components/shared", async () => {
  const actual = await vi.importActual("../components/shared");
  return {
    ...actual,
    isDemoControlsEnabled: () => mockDemoControls,
  };
});

// ── Mock WebSocket ──────────────────────────────────────────────────────────
// Trackable mock: lets tests control incoming messages and disconnection.

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

// Helper: send a JSON message to the active WS instance
function wsSend(index: number, event: string, meetingId: number, payload: Record<string, unknown> = {}) {
  const inst = wsInstances[index] ?? wsInstances[wsInstances.length - 1];
  if (!inst || !inst.onmessage) return;
  inst.onmessage({
    data: JSON.stringify({
      event,
      meeting_id: meetingId,
      timestamp: Math.floor(Date.now() / 1000),
      payload,
    }),
  });
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

beforeEach(() => {
  mockFetch.mockReset();
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("AdminDashboard - data loading", () => {
  it("shows loading state initially", () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);
    expect(screen.getByText("SmartDesk")).toBeInTheDocument();
  });

  it("loads and displays with active meeting", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1, title: "Q2 Board Review", status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse([
          { seat_id: 1, status: "checked_in", attendee_id: 1, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 2, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 3, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 4, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 5, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 6, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 7, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 8, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 9, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 10, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
        ]);
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") {
        return okResponse([
          { id: 1, meeting_id: 1, title: "Opening Remarks", sort_order: 1 },
          { id: 2, meeting_id: 1, title: "Financial Review", sort_order: 2 },
        ]);
      }
      if (url === "/api/service-calls?meeting_id=1") {
        return okResponse([{ id: 1, meeting_id: 1, seat_id: 2, service_type: "coffee", status: "pending", created_at: "2026-01-01T10:05:00Z" }]);
      }
      if (url === "/api/translations?meeting_id=1") {
        return okResponse({ meeting_id: 1, entries: [{ id: 1, meeting_id: 1, seat_id: 1, source_lang: "en", target_lang: "zh", source_text: "Good morning everyone", translated_text: "大家早上好", created_at: "2026-01-01T10:01:00Z" }] });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Q2 Board Review")).toBeInTheDocument();
    });

    expect(screen.getByText(/Conference Room.*Seat Overview/i)).toBeInTheDocument();
    expect(screen.getAllByText("Alice Wang").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Financial Review")).toBeInTheDocument();
    expect(screen.getByText(/Coffee.*Seat 2/i)).toBeInTheDocument();
    expect(screen.getByText("Good morning everyone")).toBeInTheDocument();
    expect(screen.getByText("No vote in progress")).toBeInTheDocument();
  });

  it("does not request meeting-dependent resources when no active meeting", async () => {
    const calls: string[] = [];
    mockFetch.mockImplementation((url: string) => {
      calls.push(url);
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Waiting for Meeting")).toBeInTheDocument();
    });

    expect(calls.filter((u) => u.includes("meeting_id"))).toHaveLength(0);
    expect(calls.filter((u) => u.includes("/api/meetings/1"))).toHaveLength(0);
  });
});

describe("AdminDashboard - seat display", () => {
  it("always shows 10 seats regardless of backend data", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse([
          { seat_id: 1, status: "checked_in", attendee_id: 1, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 2, status: "checked_in", attendee_id: 2, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 3, status: "checked_in", attendee_id: 3, updated_at: "2026-01-01T00:00:00Z" },
        ]);
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          { id: 1, meeting_id: 1, name: "Alice", title: "CEO", seat_id: 1, checked_in: true },
          { id: 2, meeting_id: 1, name: "Bob", title: "CTO", seat_id: 2, checked_in: true },
          { id: 3, meeting_id: 1, name: "Carol", title: "CFO", seat_id: 3, checked_in: true },
        ]);
      }
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Conference Room/i)).toBeInTheDocument();
    });

    for (let i = 1; i <= 10; i++) {
      expect(screen.getAllByText(String(i)).length).toBeGreaterThanOrEqual(1);
    }
  });
});

describe("AdminDashboard - error handling", () => {
  it("shows retry button on API error", async () => {
    mockFetch.mockRejectedValue(new Error("Network failure"));
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Failed to load data")).toBeInTheDocument();
    });
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});

describe("AdminDashboard - no mock behaviors", () => {
  it("does not render Done or clickable vote buttons", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({ id: 1, meeting_id: 1, title: "Approve Budget", options: ["Yes", "No", "Abstain"], status: "open", is_anonymous: false });
      }
      if (url === "/api/votes/1/statistics") {
        return okResponse({ vote_id: 1, title: "Approve Budget", is_anonymous: false, status: "open", total_votes: 3, results: [
          { option: "Yes", count: 2, attendee_ids: null },
          { option: "No", count: 1, attendee_ids: null },
          { option: "Abstain", count: 0, attendee_ids: null },
        ]});
      }
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Approve Budget")).toBeInTheDocument();
    });

    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
    expect(screen.queryByText("Done")).not.toBeInTheDocument();
  });

  it("shows error state when vote statistics fetch fails", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({ id: 1, meeting_id: 1, title: "Budget Vote", options: ["Yes", "No"], status: "open", is_anonymous: false });
      }
      if (url === "/api/votes/1/statistics") {
        return { ok: false, status: 500, statusText: "Internal Server Error", json: async () => ({ detail: "Stats not ready" }) };
      }
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Vote statistics unavailable")).toBeInTheDocument();
    });

    expect(screen.queryByText("0 votes cast")).not.toBeInTheDocument();
  });

  it("retry button re-fetches vote statistics on click", async () => {
    let statsCallCount = 0;
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({ id: 1, meeting_id: 1, title: "Budget Vote", options: ["Yes", "No"], status: "open", is_anonymous: false });
      }
      if (url === "/api/votes/1/statistics") {
        statsCallCount++;
        if (statsCallCount === 1) {
          return { ok: false, status: 500, statusText: "Error", json: async () => ({ detail: "Not ready" }) };
        }
        return okResponse({ vote_id: 1, title: "Budget Vote", is_anonymous: false, status: "open", total_votes: 5, results: [
          { option: "Yes", count: 3, attendee_ids: null },
          { option: "No", count: 2, attendee_ids: null },
        ]});
      }
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    // Wait for error state
    await waitFor(() => {
      expect(screen.getByText("Vote statistics unavailable")).toBeInTheDocument();
    });

    // Retry button should be present
    const retryBtn = screen.getByText("Retry");
    expect(retryBtn).toBeInTheDocument();

    // Click Retry
    await act(async () => {
      retryBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Now vote statistics should load successfully
    await waitFor(() => {
      expect(screen.getByText("5 votes cast")).toBeInTheDocument();
    });
  });
});

// ── Admin Write Operation Tests ─────────────────────────────────────────────

describe("AdminDashboard - create vote", () => {
  it("shows create vote form when there is no active vote", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      // Section title should exist (use heading role to avoid button ambiguity)
      expect(screen.getByRole("heading", { name: /Create Vote/i })).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText("Vote title...")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Option 1")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Option 2")).toBeInTheDocument();
  });

  it("calls create vote API with correct data when form is submitted", async () => {
    let postUrl = "";
    let postBody: unknown = null;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/votes" && opts?.method === "POST") {
        postUrl = url;
        postBody = opts.body ? JSON.parse(opts.body as string) : null;
        return okResponse({ id: 99, meeting_id: 1, title: "Test Vote", options: ["Yes", "No"], status: "open", is_anonymous: false });
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    // Wait for form
    await waitFor(() => {
      expect(screen.getByPlaceholderText("Vote title...")).toBeInTheDocument();
    });

    // Fill form using fireEvent
    const { fireEvent } = await import("@testing-library/react");

    await act(async () => {
      const titleInput = screen.getByPlaceholderText("Vote title...");
      fireEvent.input(titleInput, { target: { value: "Test Vote" } });

      const opt1Input = screen.getByPlaceholderText("Option 1");
      fireEvent.input(opt1Input, { target: { value: "Yes" } });

      const opt2Input = screen.getByPlaceholderText("Option 2");
      fireEvent.input(opt2Input, { target: { value: "No" } });

      await new Promise((r) => setTimeout(r, 50));
    });

    // Click create button — find by role to avoid ambiguity
    const createBtn = screen.getByRole("button", { name: /create vote/i });
    await act(async () => {
      createBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify API was called
    expect(postUrl).toBe("/api/votes");
    expect(postBody).toEqual({
      meeting_id: 1,
      title: "Test Vote",
      options: ["Yes", "No"],
      is_anonymous: false,
    });
  });

  it("shows error when creating duplicate vote returns conflict", async () => {
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/votes" && opts?.method === "POST") {
        return {
          ok: false,
          status: 409,
          json: async () => ({ detail: "OPEN_VOTE_EXISTS" }),
        };
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText("Vote title...")).toBeInTheDocument();
    });

    // Fill form and submit
    const { fireEvent } = await import("@testing-library/react");

    await act(async () => {
      const titleInput = screen.getByPlaceholderText("Vote title...");
      fireEvent.input(titleInput, { target: { value: "Duplicate Vote" } });

      const opt1Input = screen.getByPlaceholderText("Option 1");
      fireEvent.input(opt1Input, { target: { value: "A" } });

      const opt2Input = screen.getByPlaceholderText("Option 2");
      fireEvent.input(opt2Input, { target: { value: "B" } });

      await new Promise((r) => setTimeout(r, 50));
    });

    const createBtn = screen.getByRole("button", { name: /create vote/i });
    await act(async () => {
      createBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByText(/OPEN_VOTE_EXISTS/)).toBeInTheDocument();
    });
  });
});

describe("AdminDashboard - close vote", () => {
  it("shows close button for open vote and calls close API", async () => {
    let closeCalled = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/votes/1/close" && opts?.method === "POST") {
        closeCalled = true;
        return okResponse({ id: 1, meeting_id: 1, title: "Test Vote", options: ["Yes", "No"], status: "closed", is_anonymous: false });
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({ id: 1, meeting_id: 1, title: "Test Vote", options: ["Yes", "No"], status: "open", is_anonymous: false });
      }
      if (url === "/api/votes/1/statistics") {
        return okResponse({ vote_id: 1, title: "Test Vote", is_anonymous: false, status: "open", total_votes: 2, results: [
          { option: "Yes", count: 2, attendee_ids: null },
          { option: "No", count: 0, attendee_ids: null },
        ]});
      }
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Close Vote")).toBeInTheDocument();
    });

    const closeBtn = screen.getByText("Close Vote");
    await act(async () => {
      closeBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(closeCalled).toBe(true);
  });
});

describe("AdminDashboard - resolve service call", () => {
  it("shows resolve button for pending calls and calls resolve API", async () => {
    let resolveCalled = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/service-calls/1/resolve" && opts?.method === "POST") {
        resolveCalled = true;
        return okResponse({ id: 1, meeting_id: 1, seat_id: 2, service_type: "coffee", status: "resolved", created_at: "2026-01-01T10:05:00Z" });
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url === "/api/service-calls?meeting_id=1") {
        return okResponse([{ id: 1, meeting_id: 1, seat_id: 2, service_type: "coffee", status: "pending", created_at: "2026-01-01T10:05:00Z" }]);
      }
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Resolve")).toBeInTheDocument();
    });

    const resolveBtn = screen.getByText("Resolve");
    await act(async () => {
      resolveBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(resolveCalled).toBe(true);
  });
});

describe("AdminDashboard - WebSocket refresh after admin actions", () => {
  it("triggers data re-fetch when vote_closed event is received", async () => {
    let callCount = 0;

    mockFetch.mockImplementation((url: string) => {
      callCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({ id: 1, meeting_id: 1, title: "Vote", options: ["Yes", "No"], status: "open", is_anonymous: false });
      }
      if (url === "/api/votes/1/statistics") {
        return okResponse({ vote_id: 1, title: "Vote", is_anonymous: false, status: "open", total_votes: 0, results: [
          { option: "Yes", count: 0, attendee_ids: null },
          { option: "No", count: 0, attendee_ids: null },
        ]});
      }
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Vote")).toBeInTheDocument();
    });

    const initialCalls = callCount;

    // Simulate vote_closed WebSocket event
    await act(async () => {
      wsSend(0, "vote_closed", 1, { vote_id: 1 });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify re-fetch happened
    expect(callCount).toBeGreaterThan(initialCalls);
  });

  it("triggers data re-fetch when service_call_resolved event is received", async () => {
    let callCount = 0;

    mockFetch.mockImplementation((url: string) => {
      callCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) {
        return okResponse([{ id: 1, meeting_id: 1, seat_id: 2, service_type: "coffee", status: "pending", created_at: "2026-01-01T10:05:00Z" }]);
      }
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Service Requests")).toBeInTheDocument();
    });

    const initialCalls = callCount;

    // Simulate service_call_resolved WebSocket event
    await act(async () => {
      wsSend(0, "service_call_resolved", 1, { call_id: 1 });
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(callCount).toBeGreaterThan(initialCalls);
  });
});

describe("AdminDashboard - no meeting state", () => {
  it("shows waiting message and does not call meeting-dependent APIs", async () => {
    const fetchCalls: string[] = [];
    mockFetch.mockImplementation((url: string) => {
      fetchCalls.push(url);
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Waiting for Meeting")).toBeInTheDocument();
    });

    const meetingDependent = fetchCalls.filter(
      (u) => u.includes("meeting_id") || u.match(/\/api\/meetings\/\d+/),
    );
    expect(meetingDependent).toHaveLength(0);
  });
});

// ── WebSocket Behavior Tests ────────────────────────────────────────────────

describe("WebSocket - connection lifecycle", () => {
  it("creates WS connection with correct meeting ID and seat=0", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("In Progress")).toBeInTheDocument();
    });

    expect(wsInstances.length).toBeGreaterThanOrEqual(1);
    const lastWs = wsInstances[wsInstances.length - 1];
    expect(lastWs.url).toContain("/ws/1");
    expect(lastWs.url).toContain("seat=0");
  });

  it("triggers HTTP re-fetch when seat_occupied event is received", async () => {
    let callCount = 0;
    mockFetch.mockImplementation((url: string) => {
      callCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("In Progress")).toBeInTheDocument();
    });

    const initialCalls = callCount;

    await act(async () => {
      wsSend(0, "seat_occupied", 1, { seat_id: 5 });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(callCount).toBeGreaterThan(initialCalls);
    });
  });

  it("triggers HTTP re-fetch when meeting_started event is received", async () => {
    let callCount = 0;
    mockFetch.mockImplementation((url: string) => {
      callCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("In Progress")).toBeInTheDocument();
    });

    const callsBeforeEvent = callCount;

    await act(async () => {
      wsSend(0, "meeting_started", 1, { meeting_id: 1 });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(callCount).toBeGreaterThan(callsBeforeEvent);
    });
  });

  it("triggers full re-initialization after WS reconnect", async () => {
    let callCount = 0;
    mockFetch.mockImplementation((url: string) => {
      callCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("In Progress")).toBeInTheDocument();
    });

    // Record calls after initial load, then close WS to trigger reconnect
    const callsAfterInit = callCount;

    // Close WS to trigger the 3-second reconnect timer.
    // The hook's onclose will fire, setStatus("disconnected"), and
    // schedule reconnect via setTimeout(connect, 3000).
    const inst = wsInstances[wsInstances.length - 1];
    await act(async () => { inst.close(); });

    // Wait for the reconnect timer + WS reopen + async refresh
    await act(async () => {
      await new Promise((r) => setTimeout(r, 3200));
    });

    // After reconnect triggers onEvent("reconnected"), the admin hook
    // calls doFetch and HTTP call count increases.
    expect(callCount).toBeGreaterThan(callsAfterInit);
  });
});

describe("AdminDashboard - disconnected overlay", () => {
  it("does not show disconnected overlay when no meeting (no WS)", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Waiting for Meeting")).toBeInTheDocument();
    });

    expect(screen.queryByText("Connection Lost")).not.toBeInTheDocument();
  });
});

// ── Transcript WebSocket Event Tests ────────────────────────────────────────

describe("Transcript - translation_interim event", () => {
  function mockTranscriptScenario() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) {
        return okResponse({
          meeting_id: 1,
          entries: [
            { id: 1, meeting_id: 1, seat_id: 1, source_lang: "en", target_lang: "zh", source_text: "Good morning everyone", translated_text: "大家早上好", created_at: "2026-01-01T10:01:00Z" },
          ],
        });
      }
      return okResponse(null);
    });
  }

  it("shows interim subtitle after translation_interim event", async () => {
    mockTranscriptScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Send translation_interim WS event
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_1_1_000001",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "我认为这个方案需要",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Interim text should appear in the panel
    await waitFor(() => {
      expect(screen.getByText("我认为这个方案需要")).toBeInTheDocument();
    });
  });

  it("higher revision overwrites lower revision interim", async () => {
    mockTranscriptScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Send rev 1
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_1_1_000002",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "我认为这个方案",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByText("我认为这个方案")).toBeInTheDocument();
    });

    // Send rev 2 (higher) — should overwrite
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_1_1_000002",
        seat_id: 1,
        revision: 2,
        source_lang: "zh",
        target_lang: "en",
        source_text: "我认为这个方案需要重新评估",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Old text should be gone, new text should appear
    await waitFor(() => {
      expect(screen.getByText("我认为这个方案需要重新评估")).toBeInTheDocument();
    });
    expect(screen.queryByText("我认为这个方案")).not.toBeInTheDocument();
  });

  it("lower revision does not overwrite higher revision interim", async () => {
    mockTranscriptScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Send rev 5 first (higher)
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_1_1_000003",
        seat_id: 1,
        revision: 5,
        source_lang: "zh",
        target_lang: "en",
        source_text: "最新的识别结果",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByText("最新的识别结果")).toBeInTheDocument();
    });

    // Send rev 3 (lower) — should NOT overwrite
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_1_1_000003",
        seat_id: 1,
        revision: 3,
        source_lang: "zh",
        target_lang: "en",
        source_text: "旧的识别结果",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Higher revision text should persist
    expect(screen.getByText("最新的识别结果")).toBeInTheDocument();
    expect(screen.queryByText("旧的识别结果")).not.toBeInTheDocument();
  });

  it("does not trigger full HTTP refresh on translation_interim", async () => {
    let fetchCount = 0;
    mockFetch.mockImplementation((url: string) => {
      fetchCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) {
        return okResponse({ meeting_id: 1, entries: [] });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    const callsAfterLoad = fetchCount;

    // Send multiple translation_interim events
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_1_1_000004",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "测试文本",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Fetch count should NOT increase (no HTTP refresh for interims)
    expect(fetchCount).toBe(callsAfterLoad);
  });
});

describe("Transcript - translation_final event", () => {
  it("removes matching interim and shows final record", async () => {
    let initialTranslationsCall = true;
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) {
        // On first call, return empty; on subsequent calls (triggered by
        // translation_final refresh), return the final record.
        if (initialTranslationsCall) {
          initialTranslationsCall = false;
          return okResponse({ meeting_id: 1, entries: [] });
        }
        return okResponse({
          meeting_id: 1,
          entries: [
            { id: 10, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", source_text: "最终的翻译结果", translated_text: "The final translation result", created_at: "2026-01-01T10:05:00Z" },
          ],
        });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("No transcript yet")).toBeInTheDocument();
    });

    // Send translation_interim
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_1_1_000005",
        seat_id: 1,
        revision: 3,
        source_lang: "zh",
        target_lang: "en",
        source_text: "最终的翻译结果",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByText("最终的翻译结果")).toBeInTheDocument();
    });

    // Send translation_final for the same utterance_id
    await act(async () => {
      wsSend(0, "translation_final", 1, {
        utterance_id: "utt_1_1_000005",
        translation_id: 10,
        seat_id: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "最终的翻译结果",
        translated_text: "The final translation result",
        source_type: "offline_rescore",
      });
      await new Promise((r) => setTimeout(r, 200));
    });

    // The interim should be gone and the final record visible.
    // The final record is fetched via HTTP refresh triggered by translation_final.
    await waitFor(() => {
      expect(screen.getByText("The final translation result")).toBeInTheDocument();
    });
  });
});

describe("Transcript - translation_interim_cancelled event", () => {
  it("removes matching interim without adding history", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) {
        return okResponse({ meeting_id: 1, entries: [] });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("No transcript yet")).toBeInTheDocument();
    });

    // Send translation_interim
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_1_1_000006",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "被取消的中间结果",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByText("被取消的中间结果")).toBeInTheDocument();
    });

    // Send translation_interim_cancelled
    await act(async () => {
      wsSend(0, "translation_interim_cancelled", 1, {
        utterance_id: "utt_1_1_000006",
        seat_id: 1,
        reason: "speaker_seat_changed",
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Interim should be removed; "No transcript yet" should return since no entries
    await waitFor(() => {
      expect(screen.getByText("No transcript yet")).toBeInTheDocument();
    });
    expect(screen.queryByText("被取消的中间结果")).not.toBeInTheDocument();
  });
});

describe("Transcript - deduplication", () => {
  function mockScenario(translationsReturn: unknown = null) {
    const translationsData = translationsReturn ?? {
      meeting_id: 1,
      entries: [
        { id: 1, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", source_text: "Good morning everyone", translated_text: "大家早上好", created_at: "2026-01-01T10:01:00Z" },
      ],
    };
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) {
        return okResponse(translationsData);
      }
      return okResponse(null);
    });
  }

  it("same utterance_id multiple revisions only renders one interim DOM row", async () => {
    mockScenario({ meeting_id: 1, entries: [] });
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Send rev 1
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_dedup_001",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "第一版识别",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByText("第一版识别")).toBeInTheDocument();
    });

    // Send rev 2 for same utterance_id
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_dedup_001",
        seat_id: 1,
        revision: 2,
        source_lang: "zh",
        target_lang: "en",
        source_text: "第二版识别结果",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // The new text should appear and there must be exactly 1 interim row for this utterance_id
    await waitFor(() => {
      expect(screen.getByText("第二版识别结果")).toBeInTheDocument();
    });
    const interimRows = screen.getAllByTestId("transcript-interim");
    const matching = interimRows.filter(
      (el) => el.getAttribute("data-utterance-id") === "utt_dedup_001",
    );
    expect(matching).toHaveLength(1);
  });

  it("final arrival removes all interims for same utterance_id", async () => {
    let translationsCallCount = 0;
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) {
        translationsCallCount++;
        if (translationsCallCount <= 1) {
          return okResponse({ meeting_id: 1, entries: [] });
        }
        // Subsequent calls return the final record with utterance_id
        return okResponse({
          meeting_id: 1,
          entries: [
            { id: 99, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", utterance_id: "utt_dedup_002", source_text: "最终的识别结果", translated_text: "Final recognition result", created_at: "2026-01-01T10:05:00Z" },
          ],
        });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Send interim
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_dedup_002",
        seat_id: 1,
        revision: 3,
        source_lang: "zh",
        target_lang: "en",
        source_text: "最终的识别结果",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByText("最终的识别结果")).toBeInTheDocument();
    });

    // Send final
    await act(async () => {
      wsSend(0, "translation_final", 1, {
        utterance_id: "utt_dedup_002",
        translation_id: 99,
        seat_id: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "最终的识别结果",
        translated_text: "Final recognition result",
      });
      await new Promise((r) => setTimeout(r, 200));
    });

    // Interim should be gone
    await waitFor(() => {
      expect(screen.queryByTestId("transcript-interim")).not.toBeInTheDocument();
    });

    // Final should appear, exactly once
    await waitFor(() => {
      expect(screen.getByText("Final recognition result")).toBeInTheDocument();
    });
    const finalRows = screen.getAllByTestId("transcript-final");
    const matching = finalRows.filter(
      (el) => el.getAttribute("data-utterance-id") === "utt_dedup_002",
    );
    expect(matching).toHaveLength(1);
  });

  it("TranscriptPanel deduplicates same final translation id", async () => {
    // Render TranscriptPanel directly with duplicate entries
    const { TranscriptPanel } = await import("../components/TranscriptPanel");

    const dupEntries = [
      { id: 50, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", utterance_id: "utt_x", source_text: "重复文本", translated_text: "Duplicated text", created_at: "2026-01-01T10:05:00Z", source_type: null },
      { id: 50, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", utterance_id: "utt_x", source_text: "重复文本", translated_text: "Duplicated text", created_at: "2026-01-01T10:05:00Z", source_type: null },
    ];

    render(
      <TranscriptPanel
        entries={dupEntries}
        seatNameMap={{ 1: "Alice Wang" }}
      />,
    );

    // Should only render one row (deduplicated by id=50)
    const rows = screen.getAllByTestId("transcript-final");
    expect(rows).toHaveLength(1);
  });

  it("TranscriptPanel filters interims that already have a final entry", async () => {
    const { TranscriptPanel } = await import("../components/TranscriptPanel");

    const entries = [
      { id: 60, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", utterance_id: "utt_y", source_text: "最终文本", translated_text: "Final text", created_at: "2026-01-01T10:05:00Z", source_type: null },
    ];

    render(
      <TranscriptPanel
        entries={entries}
        interims={[
          { utteranceId: "utt_y", seatId: 1, revision: 5, sourceLang: "zh", targetLang: "en", sourceText: "旧中间结果", translatedText: "" },
        ]}
        seatNameMap={{ 1: "Alice Wang" }}
      />,
    );

    // The interim should NOT be rendered (filtered out because utt_y has a final entry)
    expect(screen.queryByText("旧中间结果")).not.toBeInTheDocument();
    // The final should be rendered
    expect(screen.getByText("最终文本")).toBeInTheDocument();
  });

  it("TranscriptPanel deduplicates finals by utterance_id keeping last entry", async () => {
    const { TranscriptPanel } = await import("../components/TranscriptPanel");

    const entries = [
      { id: 70, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", utterance_id: "utt_z", source_text: "旧版本", translated_text: "Old version", created_at: "2026-01-01T10:05:00Z", source_type: null },
      { id: 71, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", utterance_id: "utt_z", source_text: "新版本", translated_text: "New version", created_at: "2026-01-01T10:06:00Z", source_type: null },
    ];

    render(
      <TranscriptPanel
        entries={entries}
        seatNameMap={{ 1: "Alice Wang" }}
      />,
    );

    // Only one final row for utt_z should exist
    const rows = screen.getAllByTestId("transcript-final");
    expect(rows).toHaveLength(1);
    // The latest entry's text should be shown
    expect(screen.getByText("新版本")).toBeInTheDocument();
    expect(screen.queryByText("旧版本")).not.toBeInTheDocument();
  });
});

describe("Transcript - language labels", () => {
  it("TranscriptPanel does not render non-ASCII language labels", async () => {
    const { TranscriptPanel } = await import("../components/TranscriptPanel");

    render(
      <TranscriptPanel
        entries={[
          { id: 1, meeting_id: 1, seat_id: 1, source_lang: "zh", target_lang: "en", source_text: "你好", translated_text: "Hello", created_at: "2026-01-01T10:05:00Z", source_type: null },
          { id: 2, meeting_id: 1, seat_id: 1, source_lang: "en", target_lang: "zh", source_text: "Hi", translated_text: "嗨", created_at: "2026-01-01T10:06:00Z", source_type: null },
        ]}
        seatNameMap={{ 1: "Alice Wang" }}
      />,
    );

    // The header label should be "EN / ZH" (ASCII only)
    const headerLabel = screen.getByText("EN / ZH");
    expect(headerLabel).toBeInTheDocument();

    // Language badges should be "EN" or "ZH", never contain Chinese characters
    const badgeEls = screen.getAllByTestId("transcript-lang-label");
    expect(badgeEls.length).toBeGreaterThanOrEqual(2);
    badgeEls.forEach((el) => {
      const text = el.textContent ?? "";
      expect(text).toMatch(/^(EN|ZH)$/);
    });
  });
});
