import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { AdminDashboard } from "../components/AdminDashboard";
import { parseBackendDate, formatTranscriptTime, formatDuration } from "../components/shared";

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
    expect(screen.getByText("SmartDesk 主持人控制台")).toBeInTheDocument();
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

    // Overview workspace: conference table and attendees visible
    expect(screen.getByText(/Conference Room.*Seat Overview/i)).toBeInTheDocument();
    expect(screen.getAllByText("Alice Wang").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("设备状态 / DEVICES")).not.toBeInTheDocument();
    expect(screen.queryByText("兼容席位控制器")).not.toBeInTheDocument();
    expect(
      mockFetch.mock.calls.some(([url]) => url === "/api/hardware/status"),
    ).toBe(false);

    // Switch to agenda_vote workspace to check agenda and vote panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.getByText("Financial Review")).toBeInTheDocument();
    expect(screen.getByText("暂无投票", { exact: true })).toBeInTheDocument();

    // Switch to service_records workspace to check service and transcript panels
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.getByText(/Coffee.*Seat 2/i)).toBeInTheDocument();
    expect(screen.getByText("Good morning everyone")).toBeInTheDocument();
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
      expect(screen.getByText("No Active Meeting")).toBeInTheDocument();
    });

    expect(calls.filter((u) => u.includes("meeting_id"))).toHaveLength(0);
    expect(calls.filter((u) => u.includes("/api/meetings/1"))).toHaveLength(0);
  });
});

describe("AdminDashboard - seat display", () => {
  it("always shows 9 seats regardless of backend data", async () => {
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

    for (let i = 1; i <= 9; i++) {
      expect(screen.getByText(`SEAT ${i}`)).toBeInTheDocument();
    }
    expect(screen.queryByText("SEAT 10")).not.toBeInTheDocument();
  });
});

describe("AdminDashboard - error handling", () => {
  it("shows retry button on API error", async () => {
    mockFetch.mockRejectedValue(new Error("Network failure"));
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Failed to load data")).toBeInTheDocument();
    });
    expect(screen.getByText("重试 / Retry")).toBeInTheDocument();
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

    // Wait for meeting to load
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access vote panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

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

    // Wait for meeting to load, then switch to agenda_vote workspace
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      expect(screen.getByText(/投票统计数据不可用/)).toBeInTheDocument();
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

    // Wait for meeting to load, then switch to agenda_vote workspace
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Wait for error state
    await waitFor(() => {
      expect(screen.getByText(/投票统计数据不可用/)).toBeInTheDocument();
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

    // Wait for meeting to load, then switch to agenda_vote workspace
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      // Section title should exist (use heading role to avoid button ambiguity)
      expect(screen.getByRole("heading", { name: /Create Vote/i })).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText("投票标题 / Vote title...")).toHaveValue(
      "是否通过当前议题？ / Approve Current Agenda Item?",
    );
    expect(screen.getByPlaceholderText("选项 1 / Option 1")).toHaveValue("同意 / Approve");
    expect(screen.getByPlaceholderText("选项 2 / Option 2")).toHaveValue("反对 / Reject");
    expect(screen.getByPlaceholderText("选项 3 / Option 3")).toHaveValue("弃权 / Abstain");
    expect(
      mockFetch.mock.calls.some(
        ([url, options]) =>
          (url === "/api/votes" || url === "/api/meetings/1/agendas")
          && options?.method === "POST",
      ),
    ).toBe(false);
  });

  it("calls create vote API with correct data when form is submitted", async () => {
    let postUrl = "";
    let postBody: unknown = null;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/votes" && opts?.method === "POST") {
        postUrl = url;
        postBody = opts.body ? JSON.parse(opts.body as string) : null;
        return okResponse({ id: 99, meeting_id: 1, title: "Test Vote", options: ["Yes", "No", "Abstain"], status: "open", is_anonymous: false });
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

    // Wait for meeting to load, then switch to agenda_vote workspace
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Wait for form
    await waitFor(() => {
      expect(screen.getByPlaceholderText("投票标题 / Vote title...")).toBeInTheDocument();
    });

    // Fill form using fireEvent
    const { fireEvent } = await import("@testing-library/react");

    await act(async () => {
      const titleInput = screen.getByPlaceholderText("投票标题 / Vote title...");
      fireEvent.input(titleInput, { target: { value: "Test Vote" } });

      const opt1Input = screen.getByPlaceholderText("选项 1 / Option 1");
      fireEvent.input(opt1Input, { target: { value: "Yes" } });

      const opt2Input = screen.getByPlaceholderText("选项 2 / Option 2");
      fireEvent.input(opt2Input, { target: { value: "No" } });

      const opt3Input = screen.getByPlaceholderText("选项 3 / Option 3");
      fireEvent.input(opt3Input, { target: { value: "Abstain" } });

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
      options: ["Yes", "No", "Abstain"],
      is_anonymous: false,
    });
    expect(screen.getByPlaceholderText("投票标题 / Vote title...")).toHaveValue(
      "是否通过当前议题？ / Approve Current Agenda Item?",
    );
    expect(screen.getByPlaceholderText("选项 1 / Option 1")).toHaveValue("同意 / Approve");
    expect(screen.getByPlaceholderText("选项 2 / Option 2")).toHaveValue("反对 / Reject");
    expect(screen.getByPlaceholderText("选项 3 / Option 3")).toHaveValue("弃权 / Abstain");
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

    // Wait for meeting to load, then switch to agenda_vote workspace
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      expect(screen.getByPlaceholderText("投票标题 / Vote title...")).toBeInTheDocument();
    });

    // Fill form and submit
    const { fireEvent } = await import("@testing-library/react");

    await act(async () => {
      const titleInput = screen.getByPlaceholderText("投票标题 / Vote title...");
      fireEvent.input(titleInput, { target: { value: "Duplicate Vote" } });

      const opt1Input = screen.getByPlaceholderText("选项 1 / Option 1");
      fireEvent.input(opt1Input, { target: { value: "A" } });

      const opt2Input = screen.getByPlaceholderText("选项 2 / Option 2");
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

    // Wait for meeting to load, then switch to agenda_vote workspace
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

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

    // Wait for meeting to load, then switch to service_records workspace
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

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

    // Wait for meeting to load, then switch to agenda_vote
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

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

    // Wait for meeting to load, then switch to service_records
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

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
      expect(screen.getByText("No Active Meeting")).toBeInTheDocument();
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
      expect(screen.getByText("进行中")).toBeInTheDocument();
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
      expect(screen.getByText("进行中")).toBeInTheDocument();
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
      expect(screen.getByText("进行中")).toBeInTheDocument();
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
      expect(screen.getByText("进行中")).toBeInTheDocument();
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
      expect(screen.getByText("No Active Meeting")).toBeInTheDocument();
    });

    expect(screen.queryByText("Connection Lost")).not.toBeInTheDocument();
  });
});

// ── Speech Model Tests ────────────────────────────────────────────────────────

describe("AdminDashboard - speech model", () => {
  it("does not render Speech Model section when meeting is active", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
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
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    expect(screen.queryByText(/Speech Model/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Preload Speech Model/i)).not.toBeInTheDocument();
  });

  it("automatically triggers speech preload once when meeting is active", async () => {
    let preloadCount = 0;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/speech/preload" && opts?.method === "POST") {
        preloadCount++;
        return okResponse(null);
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
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
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Wait for the auto-preload useEffect to fire
    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });

    expect(preloadCount).toBe(1);
  });

  it("does not preload again for the same active meeting", async () => {
    let preloadCount = 0;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/speech/preload" && opts?.method === "POST") {
        preloadCount++;
        return okResponse(null);
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
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
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Wait for initial effect to fire
    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });

    expect(preloadCount).toBe(1);

    // Wait additional time to verify no duplicate preload
    await act(async () => {
      await new Promise((r) => setTimeout(r, 300));
    });

    expect(preloadCount).toBe(1);
  });

  it("does not preload speech model when there is no active meeting", async () => {
    let preloadCount = 0;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/speech/preload" && opts?.method === "POST") {
        preloadCount++;
        return okResponse(null);
      }
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("No Active Meeting")).toBeInTheDocument();
    });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });

    expect(preloadCount).toBe(0);
  });
});

// ── Bilingual Title Tests ─────────────────────────────────────────────────────

describe("AdminDashboard - bilingual titles", () => {
  it("shows Chinese-primary section titles with English secondary for major sections", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
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
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Chinese primary section titles
    expect(screen.getByText("会议控制")).toBeInTheDocument();
    expect(screen.getByText("参会人员")).toBeInTheDocument();

    // English secondary text exists
    expect(screen.getByText("MEETING CONTROL")).toBeInTheDocument();
    expect(screen.getByText("ATTENDEES")).toBeInTheDocument();
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

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
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

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
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

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
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

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
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

    // Wait for meeting to load, then switch to service_records workspace
    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      expect(screen.getByText("暂无字幕")).toBeInTheDocument();
    });

    // Send translation_interim
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_1_1_000005",
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

    // Wait for meeting to load, then switch to service_records workspace
    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      expect(screen.getByText("暂无字幕")).toBeInTheDocument();
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

    // Interim should be removed; "暂无字幕" should return since no entries
    await waitFor(() => {
      expect(screen.getByText("暂无字幕")).toBeInTheDocument();
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

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
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

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
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

// ── Live Caption Display Tests ────────────────────────────────────────────────

describe("Transcript - live caption display", () => {
  function mockCaptionScenario() {
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
  }

  it("renders two-line live caption when interim has caption", async () => {
    mockCaptionScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Send translation_interim WITH caption
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_cap_001",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "我认为这个方案需要重新评估，我们明天再讨论。",
        translated_text: "",
        is_final: false,
        caption: {
          previous_line: "我认为这个方案需要重新评估，",
          current_line: "我们明天再讨论。",
          mode: "two_line",
        },
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption block should appear
    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
      expect(screen.getByTestId("live-caption-previous")).toHaveTextContent("我认为这个方案需要重新评估，");
      expect(screen.getByTestId("live-caption-current")).toHaveTextContent("我们明天再讨论。");
    });

    // No InterimRow should be rendered for this utterance (caption replaces sourceText display)
    const interimRows = screen.queryAllByTestId("transcript-interim");
    const matchingInterimRows = interimRows.filter(
      (el) => el.getAttribute("data-utterance-id") === "utt_cap_001",
    );
    expect(matchingInterimRows).toHaveLength(0);
  });

  it("updates previous/current lines on higher revision", async () => {
    mockCaptionScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Send rev 1 — only current line
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_cap_002",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "我认为这个方案",
        translated_text: "",
        is_final: false,
        caption: {
          previous_line: "",
          current_line: "我认为这个方案",
          mode: "two_line",
        },
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByTestId("live-caption-current")).toHaveTextContent("我认为这个方案");
    });

    // Send rev 2 — previous committed, current updated
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_cap_002",
        seat_id: 1,
        revision: 2,
        source_lang: "zh",
        target_lang: "en",
        source_text: "我认为这个方案需要重新评估，我们明天再讨论。",
        translated_text: "",
        is_final: false,
        caption: {
          previous_line: "我认为这个方案需要重新评估，",
          current_line: "我们明天再讨论。",
          mode: "two_line",
        },
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Previous and current should both be updated
    await waitFor(() => {
      expect(screen.getByTestId("live-caption-previous")).toHaveTextContent("我认为这个方案需要重新评估，");
      expect(screen.getByTestId("live-caption-current")).toHaveTextContent("我们明天再讨论。");
    });
  });

  it("falls back to sourceText when caption is absent", async () => {
    mockCaptionScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Send translation_interim WITHOUT caption
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_cap_003",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "没有标点的中间结果",
        translated_text: "",
        is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption should NOT be rendered
    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();

    // Source text should appear as an InterimRow (fallback)
    await waitFor(() => {
      expect(screen.getByText("没有标点的中间结果")).toBeInTheDocument();
    });

    // The text should be inside a transcript-interim element
    const interimRow = screen.getByTestId("transcript-interim");
    expect(interimRow).toHaveTextContent("没有标点的中间结果");
  });

  it("does not render large cumulative sourceText as live paragraph when caption exists", async () => {
    mockCaptionScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Send interim with long sourceText AND caption — caption should be shown, not sourceText
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_cap_004",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "这是一个非常长的累计识别文本，不应该作为一大段live段落展示在屏幕上当caption存在的时候，因为后端已经做了分句处理。",
        translated_text: "",
        is_final: false,
        caption: {
          previous_line: "这是一个非常长的累计识别文本，",
          current_line: "不应该作为一大段live段落展示在屏幕上。",
          mode: "two_line",
        },
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Caption block should be shown
    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
      expect(screen.getByTestId("live-caption-previous")).toHaveTextContent("这是一个非常长的累计识别文本，");
      expect(screen.getByTestId("live-caption-current")).toHaveTextContent("不应该作为一大段live段落展示在屏幕上。");
    });

    // The long sourceText should NOT be rendered as an interim row
    const interimRows = screen.queryAllByTestId("transcript-interim");
    const matchingInterimRows = interimRows.filter(
      (el) => el.getAttribute("data-utterance-id") === "utt_cap_004",
    );
    expect(matchingInterimRows).toHaveLength(0);
  });

  it("live caption shows exactly two lines", async () => {
    mockCaptionScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_cap_005",
        seat_id: 1,
        revision: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "今天天气真好。",
        translated_text: "",
        is_final: false,
        caption: {
          previous_line: "今天天气真好。",
          current_line: "",
          mode: "two_line",
        },
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
    });

    // There should be exactly one previous line and one current line
    const previousEls = screen.getAllByTestId("live-caption-previous");
    const currentEls = screen.getAllByTestId("live-caption-current");
    expect(previousEls).toHaveLength(1);
    expect(currentEls).toHaveLength(1);
  });

  it("removes live caption and shows final record after translation_final", async () => {
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
        return okResponse({
          meeting_id: 1,
          entries: [
            { id: 200, meeting_id: 1, seat_id: 1, utterance_id: "utt_cap_006", source_lang: "zh", target_lang: "en", source_text: "最终的翻译结果。", translated_text: "The final translation result.", created_at: "2026-01-01T10:05:00Z", source_type: "offline_rescore" },
          ],
        });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    // Wait for meeting to load, then switch to service_records workspace
    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      expect(screen.getByText("暂无字幕")).toBeInTheDocument();
    });

    // Send interim with caption
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_cap_006",
        seat_id: 1,
        revision: 3,
        source_lang: "zh",
        target_lang: "en",
        source_text: "最终的翻译结果。",
        translated_text: "",
        is_final: false,
        caption: {
          previous_line: "最终的翻译结果。",
          current_line: "",
          mode: "two_line",
        },
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption should appear
    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
    });

    // Send translation_final for the same utterance_id
    await act(async () => {
      wsSend(0, "translation_final", 1, {
        utterance_id: "utt_cap_006",
        translation_id: 200,
        seat_id: 1,
        source_lang: "zh",
        target_lang: "en",
        source_text: "最终的翻译结果。",
        translated_text: "The final translation result.",
        source_type: "offline_rescore",
      });
      await new Promise((r) => setTimeout(r, 200));
    });

    // Live caption should be gone
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });

    // Final record should appear
    await waitFor(() => {
      expect(screen.getByText("The final translation result.")).toBeInTheDocument();
    });

    // Final record should be marked as transcript-final
    expect(screen.getByTestId("transcript-final")).toBeInTheDocument();
  });
});

describe("Transcript - language labels", () => {
  it("TranscriptPanel renders the actual bilingual translation direction", async () => {
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
      expect(text).toMatch(/^(EN → ZH|ZH → EN)$/);
    });
  });
});

// ── Task 126: Speech Lifecycle Fix Tests ───────────────────────────────────

describe("AdminDashboard - speech lifecycle fixes (Task 126)", () => {
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
        return okResponse({ meeting_id: 1, entries: [] });
      }
      return okResponse(null);
    });
  }

  // ── Admin T126-1: Late interim blocked after final ────────────────────────
  it("[T126-Admin-1] late translation_interim after final is blocked by terminal set", async () => {
    mockTranscriptScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Switch to service_records workspace
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Send interim
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_t126_admin_final_001", seat_id: 1, revision: 1,
        source_lang: "zh", target_lang: "en", source_text: "管理员端测试。",
        translated_text: "", is_final: false,
        caption: { previous_line: "", current_line: "管理员端测试。", mode: "two_line" },
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
    });

    // Send final
    await act(async () => {
      wsSend(0, "translation_final", 1, {
        translation_id: 500, utterance_id: "utt_t126_admin_final_001",
        seat_id: 1, source_lang: "zh", target_lang: "en",
        source_text: "管理员端测试。", translated_text: "Admin test.",
        source_type: "offline_rescore",
      });
      await new Promise((r) => setTimeout(r, 200));
    });

    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });

    // Send late interim — must be blocked
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_t126_admin_final_001", seat_id: 1, revision: 2,
        source_lang: "zh", target_lang: "en", source_text: "延迟到达！",
        translated_text: "", is_final: false,
        caption: { previous_line: "延迟", current_line: "到达！", mode: "two_line" },
      });
      await new Promise((r) => setTimeout(r, 200));
    });

    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
  });

  // ── Admin T126-2: Late interim blocked after cancel ───────────────────────
  it("[T126-Admin-2] late translation_interim after cancelled is blocked by terminal set", async () => {
    mockTranscriptScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Send interim
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_t126_admin_cancel_001", seat_id: 1, revision: 1,
        source_lang: "zh", target_lang: "en", source_text: "即将取消。",
        translated_text: "", is_final: false,
        caption: { previous_line: "", current_line: "即将取消。", mode: "two_line" },
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
    });

    // Send cancelled
    await act(async () => {
      wsSend(0, "translation_interim_cancelled", 1, {
        utterance_id: "utt_t126_admin_cancel_001", seat_id: 1, reason: "user_cancelled",
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });

    // Send late interim — must be blocked
    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_t126_admin_cancel_001", seat_id: 1, revision: 2,
        source_lang: "zh", target_lang: "en", source_text: "延迟抵达！",
        translated_text: "", is_final: false,
        caption: { previous_line: "延迟", current_line: "抵达！", mode: "two_line" },
      });
      await new Promise((r) => setTimeout(r, 200));
    });

    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
  });

  // ── Admin T126-3: New utterance_id still works ────────────────────────────
  it("accepts a reused utterance_id after admin WebSocket reconnect", async () => {
    mockTranscriptScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Board Meeting")).toBeInTheDocument());
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    const payload = {
      utterance_id: "utt_1_1_000001",
      seat_id: 1,
      revision: 1,
      source_lang: "zh",
      target_lang: "en",
      source_text: "first process",
      translated_text: "",
      is_final: false,
      caption: { previous_line: "", current_line: "first process", mode: "two_line" },
    };
    act(() => wsSend(0, "translation_interim", 1, payload));
    await waitFor(() => expect(screen.getByTestId("live-caption")).toBeInTheDocument());
    act(() => wsSend(0, "translation_final", 1, {
      utterance_id: payload.utterance_id,
      translation_id: 902,
      seat_id: 1,
    }));
    await waitFor(() => expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument());

    act(() => wsInstances[0].close());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 3200));
    });
    const reconnectedIndex = wsInstances.length - 1;
    act(() => wsSend(reconnectedIndex, "translation_interim", 1, {
      ...payload,
      source_text: "new backend process",
      caption: { previous_line: "", current_line: "new backend process", mode: "two_line" },
    }));
    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toHaveAttribute(
        "data-utterance-id", payload.utterance_id,
      );
    });
  }, 10000);

  it("[T126-Admin-3] new utterance_id interim still shows live caption (terminal set does not block)", async () => {
    mockTranscriptScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_t126_admin_new_001", seat_id: 1, revision: 1,
        source_lang: "zh", target_lang: "en", source_text: "新内容。",
        translated_text: "", is_final: false,
        caption: { previous_line: "", current_line: "新内容。", mode: "two_line" },
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-utterance-id", "utt_t126_admin_new_001");
    });
  });

  it("applies a trailing translation-only update to the newest source revision", async () => {
    mockTranscriptScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Board Meeting")).toBeInTheDocument());

    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await act(async () => {
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_admin_live_mt", seat_id: 1, revision: 6,
        source_lang: "zh", target_lang: "en", source_text: "管理员端最新实时识别",
        translation_source_text: "管理员端最新实时识别", translated_text: "", is_final: false,
        caption: { previous_line: "", current_line: "管理员端最新实时识别", mode: "two_line" },
      });
      wsSend(0, "translation_interim", 1, {
        utterance_id: "utt_admin_live_mt", seat_id: 1, revision: 4,
        translation_revision: 4, translation_only: true,
        source_lang: "zh", target_lang: "en", source_text: "管理员端最新实时识别",
        translation_source_text: "管理员端最新实时识别",
        translated_text: "Latest live admin translation.", is_final: false,
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(screen.getByTestId("live-caption-current")).toHaveTextContent("管理员端最新实时识别");
    expect(screen.getByTestId("live-caption-translation")).toHaveTextContent("Latest live admin translation.");
  });

  it("keeps the admin live caption mounted across automatic finalization", async () => {
    mockTranscriptScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Board Meeting")).toBeInTheDocument());
    await act(async () => {
      screen.getByText("服务与记录").click();
    });

    act(() => wsSend(0, "translation_interim", 1, {
      utterance_id: "utt_admin_roll_old", seat_id: 1, revision: 5,
      source_lang: "zh", target_lang: "en", source_text: "管理员旧段。",
      translated_text: "Old admin segment.", translation_revision: 5, caption: {
        previous_line: "管理员上一行，", current_line: "管理员旧段。", mode: "two_line",
      },
    }));
    await waitFor(() => expect(screen.getByTestId("live-caption")).toBeInTheDocument());
    const originalNode = screen.getByTestId("live-caption");

    act(() => wsSend(0, "translation_finalizing", 1, {
      utterance_id: "utt_admin_roll_old", next_utterance_id: "utt_admin_roll_next",
      seat_id: 1, source_lang: "zh", target_lang: "en",
      source_text: "管理员旧段。", boundary_reason: "soft_sentence_limit",
      rollover_overlap_ms: 300, caption: {
        previous_line: "管理员上一行，", current_line: "管理员旧段。", mode: "two_line",
      },
    }));
    await waitFor(() => {
      const live = screen.getByTestId("live-caption");
      expect(live).toBe(originalNode);
      expect(live).toHaveAttribute("data-utterance-id", "utt_admin_roll_next");
      expect(screen.queryByTestId("live-caption-placeholder")).not.toBeInTheDocument();
      expect(screen.getByTestId("live-caption-translation")).toHaveTextContent("Old admin segment.");
    });

    act(() => wsSend(0, "translation_final", 1, {
      translation_id: 880, utterance_id: "utt_admin_roll_old", seat_id: 1,
      source_lang: "zh", target_lang: "en", source_text: "管理员旧段。",
      translated_text: "Final old admin segment.", translation_status: "ok",
      source_type: "speech_ws",
    }));
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
      expect(screen.getByTestId("live-final-target")).toHaveTextContent("Final old admin segment.");
    });
  });
});

describe("AdminDashboard - seat access control", () => {
  it("shows the assigned attendee and calls manual-admit after confirmation", async () => {
    const requested: Array<{ url: string; method?: string }> = [];
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      requested.push({ url, method: options?.method });
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Access Test",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, index) => ({
          seat_id: index + 1,
          status: "vacant",
          attendee_id: null,
          updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{
          id: 7,
          meeting_id: 1,
          person_id: "person_007",
          name: "测试人员",
          title: "",
          assigned_seat_id: 1,
          seat_id: null,
          checked_in: false,
        }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url === "/api/votes/active") return okResponse(null);
      if (url.startsWith("/api/votes?")) return okResponse([]);
      if (url.startsWith("/api/service-calls")) return okResponse([]);
      if (url.startsWith("/api/translations")) {
        return okResponse({ meeting_id: 1, entries: [] });
      }
      if (url === "/api/seats/1/manual-admit") {
        return okResponse({
          seat_id: 1,
          status: "checked_in",
          attendee_id: 7,
          updated_at: "2026-01-01T00:00:00Z",
        });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);
    fireEvent.click(await screen.findByTestId("conference-seat-1"));

    const selector = await screen.findByTestId("seat-assignment-select");
    expect(selector).toHaveValue("7");
    const admit = screen.getByTestId("manual-admit-button");
    expect(admit).toBeEnabled();
    fireEvent.click(admit);

    await waitFor(() => {
      expect(requested).toContainEqual({
        url: "/api/seats/1/manual-admit",
        method: "POST",
      });
    });
    expect(window.confirm).toHaveBeenCalledWith("允许 测试人员 入座席位 1？");
  });
});

describe("AdminDashboard - sentence lyric events", () => {
  it("pairs a completed sentence translation and keeps it after final", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse({ id: 1, title: "Lyric Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([{ id: 1, meeting_id: 1, name: "Alice", seat_id: 1, checked_in: true }]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Lyric Meeting")).toBeInTheDocument());
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((resolve) => setTimeout(resolve, 30));
    });

    const base = {
      utterance_id: "utt_1_1_000001", sentence_id: "utt_1_1_000001:s000001",
      sentence_sequence: 1, seat_id: 1, revision: 4,
      source_lang: "zh", target_lang: "en", source_text: "逐句显示。",
    };
    act(() => wsSend(0, "translation_interim", 1, {
      ...base, sentence_source_text: "逐句显示。", sentence_state: "completed",
      translated_text: "", is_final: false,
    }));
    act(() => wsSend(0, "translation_sentence", 1, {
      ...base, translated_text: "Sentence display.", translation_status: "ok",
    }));
    await waitFor(() => expect(screen.getByTestId("live-lyric-translation")).toHaveTextContent("Sentence display."));

    act(() => wsSend(0, "translation_final", 1, {
      translation_id: 9, ...base, translated_text: "Final sentence display.",
    }));
    await waitFor(() => expect(screen.getByTestId("live-lyric-translation")).toHaveTextContent("Sentence display."));
  });
});

// ── Ended Meeting View Tests ───────────────────────────────────────────────

describe("AdminDashboard - ended meeting view", () => {
  function mockEndedMeetingScenario(meetingId: number) {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === ("/api/votes?meeting_id=" + meetingId)) {
        return okResponse([
          { id: 99, meeting_id: meetingId, title: "Past Vote", options: ["Yes", "No", "Abstain"], status: "closed", is_anonymous: false },
        ]);
      }
      if (url === ("/api/votes/99/statistics")) {
        return okResponse({ vote_id: 99, title: "Past Vote", is_anonymous: false, status: "closed", total_votes: 5, results: [
          { option: "Yes", count: 3, attendee_ids: null },
          { option: "No", count: 1, attendee_ids: null },
          { option: "Abstain", count: 1, attendee_ids: null },
        ]});
      }
      if (url === ("/api/meetings/" + meetingId + "/attendees")) {
        return okResponse([{ id: 10, meeting_id: meetingId, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url.includes("/api/meetings/" + meetingId + "/agendas")) return okResponse([]);
      if (url === ("/api/service-calls?meeting_id=" + meetingId)) {
        return okResponse([{ id: 1, meeting_id: meetingId, seat_id: 2, service_type: "coffee", status: "resolved", created_at: "2026-01-01T10:05:00Z" }]);
      }
      if (url === ("/api/translations?meeting_id=" + meetingId)) {
        return okResponse({ meeting_id: meetingId, entries: [{ id: 1, meeting_id: meetingId, seat_id: 1, source_lang: "en", target_lang: "zh", source_text: "Meeting ended", translated_text: "会议结束", created_at: "2026-01-01T10:10:00Z" }] });
      }
      return okResponse(null);
    });
  }

  beforeEach(() => {
    sessionStorage.removeItem("endedMeetingId");
    sessionStorage.removeItem("endedMeetingTitle");
  });

  it("shows ended meeting view when sessionStorage has endedMeetingId and no active meeting", async () => {
    sessionStorage.setItem("endedMeetingId", "42");
    sessionStorage.setItem("endedMeetingTitle", "Past Board Review");
    mockEndedMeetingScenario(42);

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getAllByText("Past Board Review").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Past Vote").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("5 votes cast").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("Meeting ended")).not.toBeInTheDocument();

    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.getByText("Meeting ended")).toBeInTheDocument();
    expect(screen.getByText("会议结束")).toBeInTheDocument();
  });

  it("uses endedMeetingId for fetching votes, translations, and service-calls", async () => {
    const calledUrls: string[] = [];
    mockFetch.mockImplementation((url: string) => {
      calledUrls.push(url);
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/votes?meeting_id=77") return okResponse([]);
      if (url === "/api/meetings/77/attendees") return okResponse([]);
      if (url.includes("/api/meetings/77/agendas")) return okResponse([]);
      if (url === "/api/service-calls?meeting_id=77") return okResponse([]);
      if (url === "/api/translations?meeting_id=77") return okResponse({ meeting_id: 77, entries: [] });
      return okResponse(null);
    });

    sessionStorage.setItem("endedMeetingId", "77");
    sessionStorage.setItem("endedMeetingTitle", "Arch Review");

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    expect(calledUrls).toContain("/api/votes?meeting_id=77");
    expect(calledUrls).toContain("/api/service-calls?meeting_id=77");
    expect(calledUrls).toContain("/api/translations?meeting_id=77");
    expect(calledUrls).toContain("/api/meetings/77/attendees");
    expect(calledUrls).toContain("/api/meetings/77/agendas");

    sessionStorage.removeItem("endedMeetingId");
    sessionStorage.removeItem("endedMeetingTitle");
  });

  it("hides all write operations in ended meeting view", async () => {
    sessionStorage.setItem("endedMeetingId", "42");
    sessionStorage.setItem("endedMeetingTitle", "Review");
    mockEndedMeetingScenario(42);

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.queryByText("结束会议 / END MEETING")).not.toBeInTheDocument();
    expect(screen.queryByText("Create Vote")).not.toBeInTheDocument();
    expect(screen.queryByText("添加参会人 / ADD ATTENDEE")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Attendee name")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Agenda title")).not.toBeInTheDocument();
    expect(screen.queryByText("Set Speaker")).not.toBeInTheDocument();
    expect(screen.queryByText("Clear Speaker")).not.toBeInTheDocument();
    expect(screen.queryByText(/Conference Room.*Seat Overview/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Connection Lost")).not.toBeInTheDocument();
    expect(screen.queryByText("Resolve")).not.toBeInTheDocument();
  });

  it("shows read-only panels in ended meeting view", async () => {
    sessionStorage.setItem("endedMeetingId", "42");
    sessionStorage.setItem("endedMeetingTitle", "Review");
    mockEndedMeetingScenario(42);

    render(
      <AdminDashboard
        hostTabletAccess={{ deviceId: "host-tablet-01", token: "device-token" }}
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getAllByText("Past Vote").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Meeting Results")).toBeInTheDocument();
    expect(screen.getByText("参会人员")).toBeInTheDocument();
    expect(screen.getAllByText(/Coffee.*Seat 2/).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("Meeting ended")).not.toBeInTheDocument();

    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.getByText("Meeting ended")).toBeInTheDocument();
    expect(screen.getAllByText("Alice Wang").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("Close Vote")).not.toBeInTheDocument();
  });

  it("does not show No Active Meeting when ended meeting data is present", async () => {
    sessionStorage.setItem("endedMeetingId", "42");
    sessionStorage.setItem("endedMeetingTitle", "Review");
    mockEndedMeetingScenario(42);

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.queryByText("No Active Meeting")).not.toBeInTheDocument();
    expect(screen.queryByText("Create Pending Meeting")).not.toBeInTheDocument();
  });

  it("clearEndedMeeting button returns to No Active Meeting view", async () => {
    sessionStorage.setItem("endedMeetingId", "42");
    sessionStorage.setItem("endedMeetingTitle", "Review");
    mockEndedMeetingScenario(42);

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    const newMeetingBtn = screen.getByText("新会议 / NEW MEETING");
    await act(async () => {
      newMeetingBtn.click();
    });

    await waitFor(() => {
      expect(screen.getByText("No Active Meeting")).toBeInTheDocument();
    });
    expect(screen.getByText("创建待启动会议 / Create Pending Meeting")).toBeInTheDocument();
    expect(sessionStorage.getItem("endedMeetingId")).toBeNull();
    expect(sessionStorage.getItem("endedMeetingTitle")).toBeNull();
  });

  it("still shows No Active Meeting when there is no ended meeting data in sessionStorage", async () => {
    sessionStorage.removeItem("endedMeetingId");
    sessionStorage.removeItem("endedMeetingTitle");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("No Active Meeting")).toBeInTheDocument();
    });
  });

  it("preserves vote results display after meeting ends", async () => {
    sessionStorage.setItem("endedMeetingId", "42");
    sessionStorage.setItem("endedMeetingTitle", "Review");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/votes?meeting_id=42") {
        return okResponse([
          { id: 55, meeting_id: 42, title: "Budget Approval", options: ["Approve", "Reject"], status: "closed", is_anonymous: false },
        ]);
      }
      if (url === "/api/votes/55/statistics") {
        return okResponse({ vote_id: 55, title: "Budget Approval", is_anonymous: false, status: "closed", total_votes: 8, results: [
          { option: "Approve", count: 6, attendee_ids: null },
          { option: "Reject", count: 2, attendee_ids: null },
        ]});
      }
      if (url === "/api/meetings/42/attendees") return okResponse([]);
      if (url.includes("/api/meetings/42/agendas")) return okResponse([]);
      if (url === "/api/service-calls?meeting_id=42") return okResponse([]);
      if (url === "/api/translations?meeting_id=42") return okResponse({ meeting_id: 42, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getAllByText("Budget Approval").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/8 votes cast/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Top: Approve")).toBeInTheDocument();
    expect(screen.getByText("1/1")).toBeInTheDocument();

    sessionStorage.removeItem("endedMeetingId");
    sessionStorage.removeItem("endedMeetingTitle");
  });
});

// ── AdminWorkspace Tests ──────────────────────────────────────────────────────

describe("AdminDashboard - AdminWorkspace", () => {
  function mockActiveMeetingScenario() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
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
  }

  it("keeps Set Speaker disabled for a vacant seat", async () => {
    mockActiveMeetingScenario();
    render(<AdminDashboard />);

    await screen.findByText("Test Meeting");
    fireEvent.click(screen.getByTestId("conference-seat-1"));

    const setSpeaker = await screen.findByRole("button", {
      name: /设为发言/,
    });
    expect(setSpeaker).toBeDisabled();
  });

  it("reports an authenticated operational heartbeat from the host tablet", async () => {
    mockActiveMeetingScenario();
    const hostTabletAccess = {
      deviceId: "host-tablet-01",
      token: "device-token",
      heartbeat: {
        seatId: 1,
        appVersion: "0.9.0",
        cameraStatus: "READY" as const,
        faceModelStatus: "READY" as const,
        registeredTemplatesCount: 1,
        microphoneStatus: "READY" as const,
        diagnosticStatus: "READY" as const,
        lastError: null,
      },
    };

    render(<AdminDashboard hostTabletAccess={hostTabletAccess} />);

    await waitFor(() => {
      const heartbeatCall = mockFetch.mock.calls.find(([url, options]) => {
        if (
          url !== "/api/tablet-devices/host-tablet-01/heartbeat"
          || typeof options?.body !== "string"
        ) return false;
        return JSON.parse(options.body).meetingWebsocketStatus === "CONNECTED";
      });
      expect(heartbeatCall).toBeDefined();
      expect(heartbeatCall?.[1]?.headers).toEqual({
        "Content-Type": "application/json",
        "X-SmartDesk-Device-Token": "device-token",
      });
      expect(JSON.parse(heartbeatCall?.[1]?.body as string)).toEqual({
        seatId: 1,
        appVersion: "0.9.0",
        cameraStatus: "READY",
        faceModelStatus: "READY",
        registeredTemplatesCount: 1,
        microphoneStatus: "READY",
        meetingWebsocketStatus: "CONNECTED",
        diagnosticStatus: "READY",
        lastError: null,
      });
    });
  });

  it("does NOT show Current Phase selector when meeting is active", async () => {
    mockActiveMeetingScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Test Meeting")).toBeInTheDocument();
    });

    // Current Phase should be completely removed
    expect(screen.queryByText("当前阶段")).not.toBeInTheDocument();
    expect(screen.queryByText("CURRENT PHASE")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "General" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Agenda Discussion" })).not.toBeInTheDocument();
  });

  it("shows three workspace switcher buttons when meeting is active", async () => {
    mockActiveMeetingScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Test Meeting")).toBeInTheDocument();
    });

    // Three workspace buttons should be visible
    expect(screen.getByText("会议总览")).toBeInTheDocument();
    expect(screen.getByText("OVERVIEW")).toBeInTheDocument();
    expect(screen.getByText("议程与投票")).toBeInTheDocument();
    expect(screen.getByText("AGENDA & VOTE")).toBeInTheDocument();
    expect(screen.getByText("服务与记录")).toBeInTheDocument();
    expect(screen.getByText("SERVICE & RECORDS")).toBeInTheDocument();
  });

  it("default workspace is overview showing conference table and attendees", async () => {
    mockActiveMeetingScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Test Meeting")).toBeInTheDocument();
    });

    // Default workspace should show conference table (overview content)
    expect(screen.getByText(/Conference Room.*Seat Overview/i)).toBeInTheDocument();
    expect(screen.getByText("参会人员")).toBeInTheDocument();
    expect(screen.getByText("ATTENDEES")).toBeInTheDocument();
  });
  it("prefills the agenda draft, submits edited text, and restores the template", async () => {
    mockActiveMeetingScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Test Meeting")).toBeInTheDocument();
    });

    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    const agendaInput = screen.getByPlaceholderText("输入议题标题 / TOPIC TITLE");
    expect(agendaInput).toHaveValue(
      "会议开场与议题确认 / Opening and Agenda Confirmation",
    );
    expect(
      mockFetch.mock.calls.some(
        ([url, options]) =>
          url === "/api/meetings/1/agendas" && options?.method === "POST",
      ),
    ).toBe(false);

    fireEvent.input(agendaInput, {
      target: { value: "董事会报告 / Board Report" },
    });
    fireEvent.click(screen.getByRole("button", { name: "添加 / ADD" }));

    await waitFor(() => {
      const call = mockFetch.mock.calls.find(
        ([url, options]) =>
          url === "/api/meetings/1/agendas" && options?.method === "POST",
      );
      expect(call).toBeDefined();
      expect(JSON.parse(call?.[1]?.body as string)).toEqual({
        title: "董事会报告 / Board Report",
        sort_order: 1,
      });
    });
    expect(agendaInput).toHaveValue(
      "会议开场与议题确认 / Opening and Agenda Confirmation",
    );
  });


  it("hides attendee management and uses a full-width host check-in row on the Seat 1 tablet", async () => {
    mockActiveMeetingScenario();
    render(
      <AdminDashboard
        hostTabletAccess={{ deviceId: "host-tablet-01", token: "device-token" }}
        hostSeatCheckIn={<div data-testid="inline-host-checkin">HOST CHECK-IN</div>}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Test Meeting")).toBeInTheDocument();
    });

    const tableHeading = screen.getByText(/Conference Room.*Seat Overview/i);
    expect(tableHeading.parentElement?.parentElement).toHaveClass("col-span-12");
    expect(tableHeading.parentElement?.parentElement).not.toHaveClass("xl:col-span-8");
    expect(screen.getByTestId("inline-host-checkin")).toBeInTheDocument();
    expect(screen.queryByText("参会人员")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("参会人姓名 / Attendee name")).not.toBeInTheDocument();
    expect(screen.getByTestId("host-checkin-layout-slot").parentElement).toHaveClass("flex", "flex-col");
    expect(screen.getByTestId("host-checkin-layout-slot").parentElement).not.toHaveClass("xl:grid-cols-2");
  });
  it("places host speech controls only in the service_records workspace", async () => {
    mockActiveMeetingScenario();
    render(
      <AdminDashboard
        hostTabletAccess={{ deviceId: "host-tablet-01", token: "device-token" }}
        hostSeatCheckIn={<div data-testid="inline-host-checkin">HOST CHECK-IN</div>}
        hostSpeechControl={<div data-testid="host-speech-control">HOST SPEECH</div>}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Test Meeting")).toBeInTheDocument();
    });

    expect(screen.getByTestId("inline-host-checkin")).toBeInTheDocument();
    expect(screen.queryByTestId("host-speech-control")).not.toBeInTheDocument();

    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(screen.queryByTestId("inline-host-checkin")).not.toBeInTheDocument();
    expect(screen.getByTestId("host-speech-control")).toBeInTheDocument();
    expect(screen.getByText("会议记录", { exact: true })).toBeInTheDocument();
  });


  it("shows meeting records only in the service_records workspace", async () => {
    mockActiveMeetingScenario();
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Test Meeting")).toBeInTheDocument();
    });

    expect(screen.queryByText("会议记录", { exact: true })).not.toBeInTheDocument();

    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.queryByText("会议记录", { exact: true })).not.toBeInTheDocument();

    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.getByText("会议记录", { exact: true })).toBeInTheDocument();

    await act(async () => {
      screen.getByText("会议总览").click();
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(screen.queryByText("会议记录", { exact: true })).not.toBeInTheDocument();
  });

  it("does not show workspace switcher when there is no active meeting", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("No Active Meeting")).toBeInTheDocument();
    });

    expect(screen.queryByText("OVERVIEW")).not.toBeInTheDocument();
    expect(screen.queryByText("AGENDA & VOTE")).not.toBeInTheDocument();
    expect(screen.queryByText("SERVICE & RECORDS")).not.toBeInTheDocument();
  });

  it("switching workspace does not trigger any API call", async () => {
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
      expect(screen.getByText("Test")).toBeInTheDocument();
    });

    const initialCalls = callCount;

    // Switch to agenda_vote workspace
    const agendaVoteBtn = screen.getByText("议程与投票");
    await act(async () => {
      agendaVoteBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Call count should NOT increase
    expect(callCount).toBe(initialCalls);

    // Switch to service_records workspace
    const serviceRecordsBtn = screen.getByText("服务与记录");
    await act(async () => {
      serviceRecordsBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(callCount).toBe(initialCalls);
  });

  it("vote creation and display unaffected by workspace switch", async () => {
    let postUrl = "";

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/votes" && opts?.method === "POST") {
        postUrl = url;
        return okResponse({ id: 99, meeting_id: 1, title: "Workspace Vote", options: ["Yes", "No"], status: "open", is_anonymous: false });
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

    // Wait for meeting to load
    await waitFor(() => {
      expect(screen.getByText("Test")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace first
    const agendaVoteBtn = screen.getByText("议程与投票");
    await act(async () => {
      agendaVoteBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Create vote form should be accessible in agenda_vote workspace
    await waitFor(() => {
      expect(screen.getByPlaceholderText("投票标题 / Vote title...")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /create vote/i })).toBeInTheDocument();

    // Fill and submit vote
    const { fireEvent } = await import("@testing-library/react");
    await act(async () => {
      fireEvent.input(screen.getByPlaceholderText("投票标题 / Vote title..."), { target: { value: "Workspace Vote" } });
      fireEvent.input(screen.getByPlaceholderText("选项 1 / Option 1"), { target: { value: "Yes" } });
      fireEvent.input(screen.getByPlaceholderText("选项 2 / Option 2"), { target: { value: "No" } });
      await new Promise((r) => setTimeout(r, 50));
    });

    const createBtn = screen.getByRole("button", { name: /create vote/i });
    await act(async () => {
      createBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(postUrl).toBe("/api/votes");
  });
});

// ── Task 4 — Helper fixes ─────────────────────────────────────────────────

describe("Task 4 — deriveAdminVoteState with closed support", () => {
  it("returns 'closed' when hasActiveVote is false but voteResults contain closed votes", async () => {
    const { deriveAdminVoteState } = await import("../utils/uiState");

    expect(deriveAdminVoteState(false, [{ status: "closed" }])).toBe("closed");
    expect(deriveAdminVoteState(false, [{ status: "open" }])).toBe("none"); // no closed vote in results
    expect(deriveAdminVoteState(false, [])).toBe("none");
    expect(deriveAdminVoteState(false)).toBe("none");
    expect(deriveAdminVoteState(true, [{ status: "closed" }])).toBe("open");
  });
});

describe("Task 4 — ended meeting + vote result: Close Vote and Resolve hidden", () => {
  function mockEndedWithData(meetingId: number) {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === ("/api/votes?meeting_id=" + meetingId)) {
        return okResponse([
          { id: 55, meeting_id: meetingId, title: "Past Vote", options: ["Yes", "No"], status: "closed", is_anonymous: false },
        ]);
      }
      if (url === ("/api/votes/55/statistics")) {
        return okResponse({ vote_id: 55, title: "Past Vote", is_anonymous: false, status: "closed", total_votes: 3, results: [
          { option: "Yes", count: 2, attendee_ids: null },
          { option: "No", count: 1, attendee_ids: null },
        ]});
      }
      if (url === ("/api/meetings/" + meetingId + "/attendees")) return okResponse([]);
      if (url.includes("/api/meetings/" + meetingId + "/agendas")) return okResponse([]);
      if (url === ("/api/service-calls?meeting_id=" + meetingId)) {
        return okResponse([{ id: 1, meeting_id: meetingId, seat_id: 1, service_type: "coffee", status: "resolved", created_at: "2026-01-01T10:05:00Z" }]);
      }
      if (url === ("/api/translations?meeting_id=" + meetingId)) {
        return okResponse({ meeting_id: meetingId, entries: [] });
      }
      return okResponse(null);
    });
  }

  beforeEach(() => {
    sessionStorage.setItem("endedMeetingId", "55");
    sessionStorage.setItem("endedMeetingTitle", "Past Review");
  });

  afterEach(() => {
    sessionStorage.removeItem("endedMeetingId");
    sessionStorage.removeItem("endedMeetingTitle");
  });

  it("does not show Close Vote button in ended meeting", async () => {
    mockEndedWithData(55);
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.queryByText("Close Vote")).not.toBeInTheDocument();
  });

  it("does not show Resolve button when no pending service calls", async () => {
    mockEndedWithData(55);
    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.queryByText("Resolve")).not.toBeInTheDocument();
  });
});

// ── Ended Meeting Snapshot & Speaker Tests ──────────────────────────────

describe("AdminDashboard - ended meeting snapshot & speaker display", () => {
  /** Set up sessionStorage with ended meeting data and optional snapshot. */
  function setupEndedSession(meetingId: number, title: string, snapshot?: unknown) {
    sessionStorage.setItem("endedMeetingId", String(meetingId));
    sessionStorage.setItem("endedMeetingTitle", title);
    if (snapshot) {
      sessionStorage.setItem(
        `smartdesk.admin.endedMeetingSnapshot.${meetingId}`,
        JSON.stringify(snapshot),
      );
    }
  }

  /** Mock an ended meeting where API returns attendees (possibly with null seat_id). */
  function mockEndedMeeting(
    meetingId: number,
    attendees: Array<{ id: number; name: string; title: string; seat_id: number | null; checked_in: boolean }>,
    translations: Array<Record<string, unknown>>,
  ) {
    const fullTranslations = translations.map((t) => ({
      meeting_id: meetingId,
      source_lang: "zh",
      target_lang: "en",
      created_at: "2026-01-01T10:10:00Z",
      ...t,
    }));
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === (`/api/votes?meeting_id=${meetingId}`)) return okResponse([]);
      if (url === (`/api/meetings/${meetingId}/attendees`)) return okResponse(attendees);
      if (url.includes(`/api/meetings/${meetingId}/agendas`)) return okResponse([]);
      if (url === (`/api/service-calls?meeting_id=${meetingId}`)) return okResponse([]);
      if (url === (`/api/translations?meeting_id=${meetingId}`)) {
        return okResponse({ meeting_id: meetingId, entries: fullTranslations });
      }
      return okResponse(null);
    });
  }

  beforeEach(() => {
    sessionStorage.removeItem("endedMeetingId");
    sessionStorage.removeItem("endedMeetingTitle");
  });

  afterEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  // ── Test 1: Save snapshot on end meeting ────────────────────────────────

  it("saves ended meeting snapshot before ending the meeting", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/meetings/1/end" && opts?.method === "POST") {
        return okResponse({ status: "finished" });
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Test Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          { id: 10, name: "张伟", title: "产品总监", seat_id: 1, checked_in: true },
          { id: 11, name: "李娜", title: "技术经理", seat_id: 2, checked_in: true },
        ]);
      }
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Test Meeting")).toBeInTheDocument();
    });

    // Click End Meeting
    await act(async () => {
      screen.getByText("结束会议 / END MEETING").click();
      await new Promise((r) => setTimeout(r, 200));
    });

    // Snapshot should be saved in sessionStorage
    const raw = sessionStorage.getItem("smartdesk.admin.endedMeetingSnapshot.1");
    expect(raw).toBeTruthy();
    const snapshot = JSON.parse(raw!);
    expect(snapshot.meetingId).toBe(1);
    expect(snapshot.attendees).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: "张伟", seat_id: 1 }),
        expect.objectContaining({ name: "李娜", seat_id: 2 }),
      ]),
    );
  });

  // ── Test 2: Ended attendees seat_id=null → display with seat ───────────

  it("shows seat number when ended attendees have seat_id=null (via snapshot)", async () => {
    const mid = 42;
    setupEndedSession(mid, "Past Review", {
      meetingId: mid,
      attendees: [
        { id: 10, name: "张伟", title: "产品总监", seat_id: 1 },
        { id: 11, name: "李娜", title: "技术经理", seat_id: 2 },
      ],
    });
    mockEndedMeeting(
      mid,
      [
        { id: 10, name: "张伟", title: "产品总监", seat_id: null, checked_in: true },
        { id: 11, name: "李娜", title: "技术经理", seat_id: null, checked_in: true },
      ],
      [],
    );

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText("张伟 · 座位 1 / Seat 1")).toBeInTheDocument();
    expect(screen.getByText("李娜 · 座位 2 / Seat 2")).toBeInTheDocument();
  });

  // ── Test 3: Ended transcript uses snapshot name ─────────────────────────

  it("shows attendee name in transcript when API seat_id is null (via snapshot)", async () => {
    const mid = 42;
    setupEndedSession(mid, "Past Review", {
      meetingId: mid,
      attendees: [
        { id: 10, name: "张伟", title: "产品总监", seat_id: 1 },
      ],
    });
    mockEndedMeeting(
      mid,
      [{ id: 10, name: "张伟", title: "产品总监", seat_id: null, checked_in: true }],
      [{ id: 100, seat_id: 1, source_text: "欢迎各位参加今天的会议", translated_text: "Welcome everyone" }],
    );

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      expect(screen.getByText("欢迎各位参加今天的会议")).toBeInTheDocument();
    });

    const finalRows = screen.getAllByTestId("transcript-final");
    const seat1Row = finalRows.find((el) => el.getAttribute("data-seat-id") === "1");
    expect(seat1Row).toBeTruthy();
    expect(seat1Row).toHaveTextContent("张伟");
    expect(seat1Row).not.toHaveTextContent("Seat 1");
  });

  // ── Test 4: No snapshot → fallback Seat N ──────────────────────────────

  it("falls back to Seat N when API has null seat_id and no snapshot", async () => {
    const mid = 88;
    setupEndedSession(mid, "Test");  // no snapshot
    mockEndedMeeting(
      mid,
      [{ id: 1, name: "Alice", title: "CEO", seat_id: null, checked_in: true }],
      [{ id: 1, seat_id: 9, source_text: "来自未知座位", translated_text: "From unknown seat" }],
    );

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      expect(screen.getByText("来自未知座位")).toBeInTheDocument();
    });

    const finalRows = screen.getAllByTestId("transcript-final");
    const seat9Row = finalRows.find((el) => el.getAttribute("data-seat-id") === "9");
    expect(seat9Row).toBeTruthy();
    expect(seat9Row).toHaveTextContent("Seat 9");
  });

  // ── Test 5: Active meeting transcript unchanged ─────────────────────────

  it("does not change active meeting transcript display", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Active Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "大苏打", title: "Developer", seat_id: 2, checked_in: true }]);
      }
      if (url.includes("/api/meetings/1/agendas")) return okResponse([]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) {
        return okResponse({
          meeting_id: 1,
          entries: [{ id: 1, meeting_id: 1, seat_id: 2, source_lang: "zh", target_lang: "en", source_text: "测试发言", translated_text: "Test speech", created_at: "2026-01-01T10:01:00Z" }],
        });
      }
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Active Meeting").length).toBeGreaterThanOrEqual(1);
    });

    // Switch to service_records workspace to access transcript
    await act(async () => {
      screen.getByText("服务与记录").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      expect(screen.getByText("测试发言")).toBeInTheDocument();
    });

    const finalRows = screen.getAllByTestId("transcript-final");
    const seat2Row = finalRows.find((el) => el.getAttribute("data-seat-id") === "2");
    expect(seat2Row).toBeTruthy();
    expect(seat2Row).toHaveTextContent("大苏打");
  });
});

// ── Phase 2 — Agenda Command Center Tests ─────────────────────────────────────

describe("AgendaCommandCenter - layout", () => {
  it("shows three-column layout: 议程控制台 / AGENDA COMMAND", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "LayoutTest", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Topic 1", sort_order: 1, status: "pending", started_at: null, completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await screen.findByText("LayoutTest");

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Three-column layout titles
    expect(screen.getByText("议程控制台")).toBeInTheDocument();
    expect(screen.getByText("AGENDA COMMAND")).toBeInTheDocument();
    expect(screen.getByText("议程时间线")).toBeInTheDocument();
    expect(screen.getByText("AGENDA TIMELINE")).toBeInTheDocument();
    expect(screen.getByText("当前议题")).toBeInTheDocument();
    expect(screen.getByText("CURRENT TOPIC")).toBeInTheDocument();
    expect(screen.getByText("议题操作")).toBeInTheDocument();
    expect(screen.getByText("TOPIC ACTIONS")).toBeInTheDocument();
  });
});

describe("AgendaCommandCenter - timeline statuses", () => {
  it("shows pending, active, completed, skipped statuses in timeline", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "TimelineTest", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Pending Topic", sort_order: 1, status: "pending", started_at: null, completed_at: null, skipped_at: null },
        { id: 2, meeting_id: 1, title: "Active Topic", sort_order: 2, status: "active", started_at: "2026-01-01T10:05:00Z", completed_at: null, skipped_at: null },
        { id: 3, meeting_id: 1, title: "Done Topic", sort_order: 3, status: "completed", started_at: "2026-01-01T10:00:00Z", completed_at: "2026-01-01T10:05:00Z", skipped_at: null },
        { id: 4, meeting_id: 1, title: "Skipped Topic", sort_order: 4, status: "skipped", started_at: null, completed_at: null, skipped_at: "2026-01-01T10:03:00Z" },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await screen.findByText("TimelineTest");

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getAllByText("Pending Topic").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Active Topic").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Done Topic").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Skipped Topic").length).toBeGreaterThanOrEqual(1);

    // Status labels — may appear in both timeline and center panel
    expect(screen.getAllByText("PENDING").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("ACTIVE").length).toBeGreaterThanOrEqual(1);

    // The center panel shows current (active) agenda
    expect(screen.getByText("当前议题")).toBeInTheDocument();
  });
});

describe("AgendaCommandCenter - preview behavior", () => {
  it("clicking timeline item only previews, does not call set-current API", async () => {
    const postCalls: string[] = [];

    mockFetch.mockImplementation((url: string, _opts?: RequestInit) => {
      if (_opts?.method === "POST" && url.includes("set-current")) {
        postCalls.push(url);
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "PreviewTest", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Item A", sort_order: 1, status: "pending", started_at: null, completed_at: null, skipped_at: null },
        { id: 2, meeting_id: 1, title: "Item B", sort_order: 2, status: "pending", started_at: null, completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await screen.findByText("PreviewTest");

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Click on "Item A" in the timeline
    const itemA = screen.getByText("Item A");
    await act(async () => {
      itemA.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Should show preview, NOT call set-current
    expect(screen.getByText(/PREVIEW ONLY/)).toBeInTheDocument();
    expect(postCalls).toHaveLength(0);
  });
});

describe("AgendaCommandCenter - set current actions", () => {
  it("preview pending then Set Current calls correct API", async () => {
    let setCurrentCalledWith = 0;
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && url.includes("set-current")) {
        setCurrentCalledWith = Number(url.match(/agendas\/(\d+)\/set-current/)?.[1] ?? 0);
        return okResponse(null);
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Pending Item", sort_order: 1, status: "pending", started_at: null, completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Click pending item to preview
    await act(async () => {
      screen.getByText("Pending Item").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // "Set Current" button should be visible
    const setCurrentBtn = screen.getByText(/SET CURRENT/);
    expect(setCurrentBtn).toBeInTheDocument();

    // Click Set Current
    await act(async () => {
      setCurrentBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(setCurrentCalledWith).toBe(1);
  });

  it("preview skipped then Set Current calls correct API", async () => {
    let setCurrentCalledWith = 0;
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && url.includes("set-current")) {
        setCurrentCalledWith = Number(url.match(/agendas\/(\d+)\/set-current/)?.[1] ?? 0);
        return okResponse(null);
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 5, meeting_id: 1, title: "Skipped Item", sort_order: 1, status: "skipped", started_at: null, completed_at: null, skipped_at: "2026-01-01T10:03:00Z" },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Click skipped item
    await act(async () => {
      screen.getByText("Skipped Item").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    const setCurrentBtn = screen.getByText(/SET CURRENT/);
    expect(setCurrentBtn).toBeInTheDocument();

    await act(async () => {
      setCurrentBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(setCurrentCalledWith).toBe(5);
  });

  it("preview completed shows Set Current disabled/explanation", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 3, meeting_id: 1, title: "Completed Item", sort_order: 1, status: "completed", started_at: "2026-01-01T10:00:00Z", completed_at: "2026-01-01T10:05:00Z", skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await screen.findByText("AgendaMtg");

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Click completed item
    await act(async () => {
      screen.getByText("Completed Item").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Should show explanation text, not Set Current button
    expect(screen.getByText(/COMPLETED TOPICS CANNOT BE SET CURRENT/)).toBeInTheDocument();
  });

  it("switching from existing active shows confirm; cancel does not call API", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    let setCurrentCalled = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && url.includes("set-current")) {
        setCurrentCalled = true;
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Current Active", sort_order: 1, status: "active", started_at: "2026-01-01T10:00:00Z", completed_at: null, skipped_at: null },
        { id: 2, meeting_id: 1, title: "Next Topic", sort_order: 2, status: "pending", started_at: null, completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Preview next topic
    await act(async () => {
      screen.getByText("Next Topic").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Click Set Current → confirm dialog appears
    const setCurrentBtn = screen.getByText(/SET CURRENT/);
    await act(async () => {
      setCurrentBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Confirm should have been called, but returned false (cancelled)
    expect(confirmSpy).toHaveBeenCalled();
    expect(setCurrentCalled).toBe(false);

    confirmSpy.mockRestore();
  });

  it("switching with active and confirm=true calls API", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    let setCurrentCalled = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && url.includes("set-current")) {
        setCurrentCalled = true;
        return okResponse(null);
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Current Active", sort_order: 1, status: "active", started_at: "2026-01-01T10:00:00Z", completed_at: null, skipped_at: null },
        { id: 2, meeting_id: 1, title: "Next Topic", sort_order: 2, status: "pending", started_at: null, completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Preview next topic
    await act(async () => {
      screen.getByText("Next Topic").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Click Set Current
    const setCurrentBtn = screen.getByText(/SET CURRENT/);
    await act(async () => {
      setCurrentBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(confirmSpy).toHaveBeenCalled();
    expect(setCurrentCalled).toBe(true);

    confirmSpy.mockRestore();
  });
});

describe("AgendaCommandCenter - advance, complete, skip", () => {
  it("Advance is disabled when no active agenda", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Pending Item", sort_order: 1, status: "pending", started_at: null, completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Advance button should be disabled (no active agenda)
    const advanceBtn = screen.getByText(/ADVANCE/).closest("button");
    expect(advanceBtn).toBeDisabled();
  });

  it("Advance with active agenda calls correct API", async () => {
    let advanceCalled = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && url.includes("advance")) {
        advanceCalled = true;
        return okResponse(null);
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Active Item", sort_order: 1, status: "active", started_at: "2026-01-01T10:00:00Z", completed_at: null, skipped_at: null },
        { id: 2, meeting_id: 1, title: "Next Item", sort_order: 2, status: "pending", started_at: null, completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Advance button should be enabled
    const advanceBtn = screen.getByText(/ADVANCE/).closest("button");
    expect(advanceBtn).not.toBeDisabled();

    await act(async () => {
      advanceBtn!.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(advanceCalled).toBe(true);
  });

  it("Complete only available when active agenda exists", async () => {
    let completeCalled = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && url.includes("complete")) {
        completeCalled = true;
        return okResponse(null);
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Active Item", sort_order: 1, status: "active", started_at: "2026-01-01T10:00:00Z", completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Click Complete
    const completeBtn = screen.getByText(/COMPLETE/).closest("button");
    expect(completeBtn).not.toBeDisabled();

    await act(async () => {
      completeBtn!.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(completeCalled).toBe(true);
  });

  it("Skip with active agenda shows confirm and calls API", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    let skipCalled = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && url.includes("skip")) {
        skipCalled = true;
        return okResponse(null);
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Active Item", sort_order: 1, status: "active", started_at: "2026-01-01T10:00:00Z", completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Click Skip
    const skipBtn = screen.getByText(/SKIP/).closest("button");
    expect(skipBtn).not.toBeDisabled();

    await act(async () => {
      skipBtn!.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(confirmSpy).toHaveBeenCalled();
    expect(skipCalled).toBe(true);

    confirmSpy.mockRestore();
  });

  it("Skip with active but cancel confirm does not call API", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    let skipCalled = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST" && url.includes("skip")) {
        skipCalled = true;
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Active Item", sort_order: 1, status: "active", started_at: "2026-01-01T10:00:00Z", completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    const skipBtn = screen.getByText(/SKIP/).closest("button");
    await act(async () => {
      skipBtn!.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(confirmSpy).toHaveBeenCalled();
    expect(skipCalled).toBe(false);

    confirmSpy.mockRestore();
  });
});

describe("AgendaCommandCenter - flow done state", () => {
  it("shows 所有议题已处理 / ALL TOPICS PROCESSED when all processed", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Topic A", sort_order: 1, status: "completed", started_at: "2026-01-01T10:00:00Z", completed_at: "2026-01-01T10:05:00Z", skipped_at: null },
        { id: 2, meeting_id: 1, title: "Topic B", sort_order: 2, status: "skipped", started_at: null, completed_at: null, skipped_at: "2026-01-01T10:03:00Z" },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByText("所有议题已处理")).toBeInTheDocument();
    expect(screen.getByText("ALL TOPICS PROCESSED")).toBeInTheDocument();
  });
});

describe("AgendaCommandCenter - meeting ended", () => {
  beforeEach(() => {
    sessionStorage.setItem("endedMeetingId", "42");
    sessionStorage.setItem("endedMeetingTitle", "Past Meeting");
  });

  afterEach(() => {
    sessionStorage.removeItem("endedMeetingId");
    sessionStorage.removeItem("endedMeetingTitle");
  });

  it("hides all control buttons when meeting ended", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/votes?meeting_id=42") return okResponse([]);
      if (url === "/api/meetings/42/attendees") return okResponse([]);
      if (url.includes("/api/meetings/42/agendas")) return okResponse([
        { id: 1, meeting_id: 42, title: "Past Topic", sort_order: 1, status: "completed", started_at: "2026-01-01T10:00:00Z", completed_at: "2026-01-01T10:05:00Z", skipped_at: null },
      ]);
      if (url === "/api/service-calls?meeting_id=42") return okResponse([]);
      if (url === "/api/translations?meeting_id=42") return okResponse({ meeting_id: 42, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByText("Meeting Ended").length).toBeGreaterThanOrEqual(1);
    });

    // The agenda panel should be visible but with read-only message
    expect(screen.getByText("会议已结束，议程只读")).toBeInTheDocument();
    expect(screen.getByText("READ-ONLY")).toBeInTheDocument();

    // Control buttons should NOT be present
    expect(screen.queryByText("SET CURRENT")).not.toBeInTheDocument();
    expect(screen.queryByText("ADVANCE")).not.toBeInTheDocument();
    expect(screen.queryByText("COMPLETE")).not.toBeInTheDocument();
    expect(screen.queryByText("SKIP")).not.toBeInTheDocument();
  });
});

describe("AgendaCommandCenter - delete active agenda disabled", () => {
  it("delete button is disabled/not shown for active agenda", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) return okResponse([
        { id: 1, meeting_id: 1, title: "Active Item", sort_order: 1, status: "active", started_at: "2026-01-01T10:00:00Z", completed_at: null, skipped_at: null },
      ]);
      if (url.includes("/api/service-calls")) return okResponse([]);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Preview the active item (click first match in timeline)
    await act(async () => {
      const items = screen.getAllByText("Active Item");
      items[0].click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Delete button should NOT be visible for active agenda
    expect(screen.queryByText(/DELETE/)).not.toBeInTheDocument();
  });
});

describe("AgendaCommandCenter - WebSocket agenda_updated", () => {
  it("triggers HTTP re-fetch when matching agenda_updated received", async () => {
    let callCount = 0;
    mockFetch.mockImplementation((url: string) => {
      callCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
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
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    const initialCalls = callCount;

    // Send agenda_updated with matching meeting_id=1
    await act(async () => {
      wsSend(0, "agenda_updated", 1, {});
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(callCount).toBeGreaterThan(initialCalls);
    });
  });

  it("ignores agenda_updated when meeting_id does not match", async () => {
    let callCount = 0;
    mockFetch.mockImplementation((url: string) => {
      callCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "AgendaMtg", status: "active", started_at: "2026-01-01T10:00:00Z" });
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
      expect(screen.getByText("AgendaMtg")).toBeInTheDocument();
    });

    // Switch to agenda_vote workspace to access agenda panels
    await act(async () => {
      screen.getByText("议程与投票").click();
      await new Promise((r) => setTimeout(r, 50));
    });

    const initialCalls = callCount;

    // Send agenda_updated with non-matching meeting_id=99
    await act(async () => {
      wsSend(0, "agenda_updated", 99, {});
      await new Promise((r) => setTimeout(r, 100));
    });

    // Wait a bit to ensure no re-fetch
    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });

    // Call count should NOT have increased
    expect(callCount).toBe(initialCalls);
  });
});

// ── Speech Preload Tests (Task 6) ───────────────────────────────────────────

// Speech model preload tests moved to "AdminDashboard - speech model" describe block above

// ── Task 130: Time Display Correctness Tests ───────────────────────────────

describe("parseBackendDate — naive UTC parsing", () => {
  it("treats naive UTC string as UTC, not local time", () => {
    // "2026-01-01T04:27:00" has NO "Z".  parseBackendDate must treat it as
    // UTC (append "Z"), NOT as local time, otherwise it would be wrong by the
    // local UTC offset (e.g. 8 hours in UTC+8).
    const d = parseBackendDate("2026-01-01T04:27:00");
    expect(d).not.toBeNull();

    // The resulting Date should represent 04:27 UTC
    expect(d!.getUTCHours()).toBe(4);
    expect(d!.getUTCMinutes()).toBe(27);

    // Its numeric timestamp must equal what we'd get with explicit "Z"
    const withZ = new Date("2026-01-01T04:27:00Z");
    expect(d!.getTime()).toBe(withZ.getTime());
  });

  it("parses Z-suffixed string correctly", () => {
    const d = parseBackendDate("2026-01-01T04:27:00Z");
    expect(d).not.toBeNull();
    expect(d!.getUTCHours()).toBe(4);
    expect(d!.getUTCMinutes()).toBe(27);
  });

  it("parses timezone-offset string correctly", () => {
    // +08:00 → 12:27 local = 04:27 UTC
    const d = parseBackendDate("2026-01-01T12:27:00+08:00");
    expect(d).not.toBeNull();
    expect(d!.getUTCHours()).toBe(4);
    expect(d!.getUTCMinutes()).toBe(27);
  });

  it("returns null for null / undefined / empty string", () => {
    expect(parseBackendDate(null)).toBeNull();
    expect(parseBackendDate(undefined)).toBeNull();
    expect(parseBackendDate("")).toBeNull();
  });

  it("returns null for an invalid date string", () => {
    expect(parseBackendDate("not-a-date")).toBeNull();
    expect(parseBackendDate("2026-13-01T00:00:00")).toBeNull(); // month 13
  });
});

describe("formatTranscriptTime — transcript time display", () => {
  it("formats a naive UTC string as HH:mm (local time)", () => {
    // 2026-01-01T04:27:00 treated as UTC → converted to local in HH:mm
    const result = formatTranscriptTime("2026-01-01T04:27:00");
    expect(result).toMatch(/^\d{2}:\d{2}$/);
    // Must NOT contain "AM" or "PM" (hour12: false)
    expect(result).not.toMatch(/AM|PM/);
  });

  it("formats Z-suffixed string as HH:mm (local time)", () => {
    const result = formatTranscriptTime("2026-01-01T04:27:00Z");
    expect(result).toMatch(/^\d{2}:\d{2}$/);
    expect(result).not.toMatch(/AM|PM/);
  });

  it("returns --:-- fallback for null / undefined / empty", () => {
    expect(formatTranscriptTime(null)).toBe("--:--");
    expect(formatTranscriptTime(undefined)).toBe("--:--");
    expect(formatTranscriptTime("")).toBe("--:--");
  });
});

describe("AdminDashboard - elapsed time display (Task 130)", () => {
  beforeEach(() => {
    // Clean up any ended-meeting sessionStorage left by previous tests
    try {
      sessionStorage.removeItem('endedMeetingId');
      sessionStorage.removeItem('endedMeetingTitle');
      sessionStorage.removeItem('endedMeetingStartedAt');
      sessionStorage.removeItem('endedMeetingEndedAt');
    } catch { /* sessionStorage may throw */ }
  });

  it("shows Meeting time MetricCard with formatted elapsed for active meeting", async () => {
    // started_at is 5 minutes in the past (naive UTC — no "Z")
    const fiveMinAgo = new Date();
    fiveMinAgo.setMinutes(fiveMinAgo.getMinutes() - 5);
    const naiveUtc = fiveMinAgo.toISOString().replace("Z", ""); // strip Z

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1, title: "Time Test", status: "active",
          started_at: naiveUtc,
        });
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
      expect(screen.getByText("Time Test")).toBeInTheDocument();
    });

    // The bilingual MetricCard should show elapsed (with non-zero value from 5 min ago)
    const meetingTime = screen.getByText("会议时长");
    expect(screen.getByText("MEETING TIME")).toBeInTheDocument();

    // The MetricCard value (previous sibling inside the same container) should be a
    // formatted duration, not "--"
    const elapsedValue = meetingTime.parentElement?.previousElementSibling;
    expect(elapsedValue).toBeTruthy();
    expect(elapsedValue!.textContent).not.toBe("—");
    expect(elapsedValue!.textContent).toMatch(/^\d/); // starts with a digit
  });

  it("shows Duration in ended meeting banner with static elapsed", async () => {
    const effectiveMeetingId = 99;

    // Ended meeting: fetchActiveMeeting returns null; meeting-dependent
    // endpoints also need valid empty responses.
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      // Meeting-dependent endpoints (effectiveMeetingId = 99)
      if (url === `/api/meetings/${effectiveMeetingId}/attendees`) return okResponse([]);
      if (url === `/api/meetings/${effectiveMeetingId}/agendas`) return okResponse([]);
      if (url === `/api/service-calls?meeting_id=${effectiveMeetingId}`) return okResponse([]);
      if (url === `/api/translations?meeting_id=${effectiveMeetingId}`) return okResponse({ meeting_id: effectiveMeetingId, entries: [] });
      if (url === `/api/votes?meeting_id=${effectiveMeetingId}`) return okResponse([]);
      return okResponse(null);
    });

    // Pre-populate sessionStorage so the ended meeting is restored
    try {
      sessionStorage.setItem('endedMeetingId', String(effectiveMeetingId));
      sessionStorage.setItem('endedMeetingTitle', 'Ended Meeting');
      sessionStorage.setItem('endedMeetingStartedAt', '2026-01-01T10:00:00'); // naive UTC
      sessionStorage.setItem('endedMeetingEndedAt', '2026-01-01T11:30:00');   // naive UTC → 1h30m
    } catch { /* sessionStorage may throw */ }

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Meeting Ended")).toBeInTheDocument();
    });

    // Duration should show "1:30:00" (1h30m = 5400000 ms in HH:mm:ss format)
    await waitFor(() => {
      const durationElem = screen.getByText((content) => content.includes('Duration:'));
      expect(durationElem).toBeInTheDocument();
      expect(durationElem.textContent).toContain('1:30:00');
    });

    // Cleanup sessionStorage
    try {
      sessionStorage.removeItem('endedMeetingId');
      sessionStorage.removeItem('endedMeetingTitle');
      sessionStorage.removeItem('endedMeetingStartedAt');
      sessionStorage.removeItem('endedMeetingEndedAt');
    } catch { /* sessionStorage may throw */ }
  });

  it("does NOT show elapsed when there is no meeting", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<AdminDashboard onSwitchToSeat={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("No Active Meeting")).toBeInTheDocument();
    });

    // No bilingual Meeting Time metric should exist
    expect(screen.queryByText("会议时长")).not.toBeInTheDocument();
    expect(screen.queryByText("MEETING TIME")).not.toBeInTheDocument();
  });

  it("formatDuration handles exactly 1 hour", () => {
    // 3600 seconds = 3600000 ms
    expect(formatDuration(3600000)).toBe("1:00:00");
  });

  it("formatDuration handles under 1 hour", () => {
    // 5 minutes 30 seconds = 330000 ms
    expect(formatDuration(330000)).toBe("05:30");
  });
});
