/// <reference types="vitest" />
import { render, screen, waitFor } from "@testing-library/react";
import App from "../App";

// ── Mock isDemoControlsEnabled ───────────────────────────────────────────────
vi.mock("../components/shared", async () => {
  const actual = await vi.importActual("../components/shared");
  return {
    ...actual,
    isDemoControlsEnabled: () => false,
  };
});

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

/** Helper: create a fetch Response for the success:true ApiResponse envelope. */
function okResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, message: "OK", data }),
  };
}

beforeEach(() => {
  mockFetch.mockReset();
  // Reset URL to default
  window.history.replaceState({}, "", "/");
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

// ── Tests ───────────────────────────────────────────────────────────────────

describe("App - admin mode (default)", () => {
  it("renders admin dashboard with data from backend API", async () => {
    // Mock an active meeting scenario
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Board Meeting",
          description: null,
          status: "active",
          created_at: "2026-01-01T00:00:00Z",
          started_at: "2026-01-01T10:00:00Z",
          ended_at: null,
        });
      }
      if (url === "/api/seats") {
        return okResponse([
          { seat_id: 1, status: "checked_in", attendee_id: 1, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 2, status: "checked_in", attendee_id: 2, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 3, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 4, status: "occupied_unchecked", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 5, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 6, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 7, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 8, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 9, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
          { seat_id: 10, status: "vacant", attendee_id: null, updated_at: "2026-01-01T00:00:00Z" },
        ]);
      }
      if (url === "/api/seats/speaker") {
        return okResponse({ seat_id: 1 });
      }
      if (url === "/api/votes/active") {
        return okResponse(null);
      }
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          { id: 1, meeting_id: 1, name: "Alice", title: "CEO", seat_id: 1, checked_in: true },
          { id: 2, meeting_id: 1, name: "Bob", title: "CTO", seat_id: 2, checked_in: true },
        ]);
      }
      if (url === "/api/meetings/1/agendas") {
        return okResponse([
          { id: 1, meeting_id: 1, title: "Call to Order", sort_order: 1 },
        ]);
      }
      if (url === "/api/service-calls?meeting_id=1") {
        return okResponse([]);
      }
      if (url === "/api/translations?meeting_id=1") {
        return okResponse({ meeting_id: 1, entries: [] });
      }
      return okResponse(null);
    });

    render(<App />);

    // Should show SmartDesk brand
    expect(screen.getByText("SmartDesk")).toBeInTheDocument();

    // Should eventually show the conference table and meeting title
    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText(/Conference Table/i)).toBeInTheDocument();
    });

    // Should show meeting summary metrics (Elapsed, Attendees)
    expect(screen.getByText("Elapsed")).toBeInTheDocument();
    expect(screen.getByText("Attendees")).toBeInTheDocument();

    // Should show 2/10 checked in
    expect(screen.getByText("2/10")).toBeInTheDocument();
  });

  it("shows waiting state when no active meeting", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse(null);
      }
      if (url === "/api/seats") return okResponse([]);
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      return okResponse(null);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Waiting for Meeting")).toBeInTheDocument();
    });
  });

  it("shows error state with retry button when API fails", async () => {
    mockFetch.mockRejectedValue(new TypeError("Failed to fetch"));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Failed to load data")).toBeInTheDocument();
    });

    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});

describe("App - seat mode via URL (no VITE_ENABLE_DEMO_CONTROLS)", () => {
  it("switches to seat tablet when ?seat=1 is provided", async () => {
    window.history.replaceState({}, "", "/?seat=1");

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1, title: "Board Meeting", status: "active",
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
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Seat 1")).toBeInTheDocument();
    });

    // Should show Back button
    expect(screen.getByText("Back")).toBeInTheDocument();
  });

  it("shows error page for invalid seat parameter", async () => {
    window.history.replaceState({}, "", "/?seat=invalid");
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Invalid Seat Selection")).toBeInTheDocument();
    });
    expect(screen.getByText(/Seat must be an integer between 1 and 10/i)).toBeInTheDocument();
    expect(screen.getByText("Back to Admin Dashboard")).toBeInTheDocument();
  });

  it("shows error for seat=0 (out of range)", async () => {
    window.history.replaceState({}, "", "/?seat=0");
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Invalid Seat Selection")).toBeInTheDocument();
    });
  });

  it("shows error for seat=11 (out of range)", async () => {
    window.history.replaceState({}, "", "/?seat=11");
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Invalid Seat Selection")).toBeInTheDocument();
    });
  });
});
