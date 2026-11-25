/// <reference types="vitest" />
/**
 * Task 2 — DisplayView ended meeting tests.
 *
 * Prerequisites:
 *   - The DisplayView component is mounted at /display.
 *   - Tests mock the global fetch and WebSocket APIs.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DisplayView } from "../components/DisplayView";

// ── Mock fetch ────────────────────────────────────────────────────────────────

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function okResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, message: "OK", data }),
  };
}

// ── Mock WebSocket ────────────────────────────────────────────────────────────

let wsInstances: ReturnType<typeof createMockWsInstance>[] = [];

function createMockWsInstance(url: string) {
  return {
    url,
    onopen: null as (() => void) | null,
    onclose: null as (() => void) | null,
    onmessage: null as ((ev: { data: string }) => void) | null,
    onerror: null as (() => void) | null,
    readyState: 0,
    close: vi.fn(),
    send: vi.fn(),
  };
}

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
    const inst = createMockWsInstance(url);
    inst.onopen = null;
    inst.onclose = null;
    inst.onmessage = null;
    inst.onerror = null;
    Object.assign(this, inst);
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

function simulateWsEvent(message: object) {
  for (const ws of wsInstances) {
    if (ws.onmessage) {
      ws.onmessage({ data: JSON.stringify(message) });
    }
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function activeMeeting(overrides: Partial<{ id: number; title: string }> = {}) {
  return {
    id: overrides.id ?? 1,
    title: overrides.title ?? "Board Meeting",
    description: null,
    status: "active" as const,
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T10:00:00Z",
    ended_at: null,
  };
}

function closedVoteStats() {
  return {
    vote_id: 10,
    title: "Floor Color",
    is_anonymous: false,
    status: "closed" as const,
    total_votes: 5,
    results: [
      { option: "Blue", count: 3, attendee_ids: [1, 2, 3] },
      { option: "Red", count: 2, attendee_ids: [4, 5] },
    ],
  };
}

function openVoteStats() {
  return {
    vote_id: 11,
    title: "Lunch Choice",
    is_anonymous: false,
    status: "open" as const,
    total_votes: 2,
    results: [
      { option: "Pizza", count: 1, attendee_ids: [1] },
      { option: "Salad", count: 1, attendee_ids: [2] },
    ],
  };
}

function renderDisplay() {
  return render(
    <MemoryRouter initialEntries={["/display"]}>
      <DisplayView />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  wsInstances = [];
  globalThis.WebSocket = TrackedMockWebSocket as unknown as typeof WebSocket;
  sessionStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("DisplayView — Task 2 ended meeting", () => {
  it("recovers missed agenda updates after the meeting socket reconnects", async () => {
    let agendaTitle = "First topic";
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(activeMeeting());
      if (url === "/api/meetings/1/agendas") return okResponse([
        { id: 1, title: agendaTitle, sort_order: 1, status: "active" },
      ]);
      if (url.startsWith("/api/votes?")) return okResponse([]);
      return okResponse(null);
    });
    renderDisplay();
    await screen.findAllByText("First topic");
    await waitFor(() => expect(wsInstances[0]?.readyState).toBe(1));
    agendaTitle = "Updated while offline";
    act(() => wsInstances[0].onclose?.());
    expect(await screen.findAllByText(agendaTitle, {}, { timeout: 4500 })).toHaveLength(2);
  });

  it("1. active meeting exists → shows vote results", async () => {
    mockFetch
      .mockResolvedValueOnce(okResponse(activeMeeting()))
      .mockResolvedValueOnce(okResponse(null)) // fetchActiveVote → null
      .mockResolvedValueOnce(okResponse([{ id: 10, meeting_id: 1, title: "Floor Color", options: ["Blue", "Red"], status: "closed", is_anonymous: false }])) // fetchVotesForMeeting
      .mockResolvedValueOnce(okResponse([])) // fetchAgendas(1)
      .mockResolvedValueOnce(okResponse(closedVoteStats())); // fetchVoteStatistics for vote 10

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("Floor Color")).toBeInTheDocument();
      expect(screen.getByText("Blue")).toBeInTheDocument();
      expect(screen.getByText("Red")).toBeInTheDocument();
    });

    // Should NOT show the ended-meeting banner.
    expect(screen.queryByText(/会议已结束/)).not.toBeInTheDocument();
  });

  it("2. no active meeting, no endedMeetingId → waiting state", async () => {
    mockFetch
      .mockResolvedValueOnce(okResponse(null)); // fetchActiveMeeting → null

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Waiting for Meeting")).toBeInTheDocument();
    });

    // Should show no-votes state
    await waitFor(() => {
      expect(screen.getByText("暂无投票")).toBeInTheDocument();
    });

    // Should NOT show the ended-meeting banner.
    expect(screen.queryByText(/会议已结束/)).not.toBeInTheDocument();
  });

  it("3. meeting_ended WS event → saves endedMeetingId, shows Meeting Ended with vote results", async () => {
    // First render: active meeting exists
    mockFetch
      .mockResolvedValueOnce(okResponse(activeMeeting({ id: 1, title: "Board Meeting" }))) // fetchActiveMeeting
      .mockResolvedValueOnce(okResponse(null)) // fetchActiveVote → null
      .mockResolvedValueOnce(okResponse([{ id: 10, meeting_id: 1, title: "Floor Color", options: ["Blue", "Red"], status: "closed", is_anonymous: false }])) // fetchVotesForMeeting
      .mockResolvedValueOnce(okResponse([])) // fetchAgendas(1)
      .mockResolvedValueOnce(okResponse(closedVoteStats())); // fetchVoteStatistics

    renderDisplay();

    // Wait for initial render
    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    // Simulate meeting_ended WS event
    // After meeting_ended, the load function will be called again
    // The second load call should see no active meeting
    mockFetch
      .mockReset()
      .mockResolvedValueOnce(okResponse(null)) // fetchActiveMeeting → null (meeting ended)
      .mockResolvedValueOnce(okResponse([{ id: 10, meeting_id: 1, title: "Floor Color", options: ["Blue", "Red"], status: "closed", is_anonymous: false }])) // fetchVotesForMeeting(1)
      .mockResolvedValueOnce(okResponse([])) // fetchAgendas(endedMeetingId)
      .mockResolvedValueOnce(okResponse(closedVoteStats())); // fetchVoteStatistics(10)

    // Trigger meeting_ended event
    await act(async () => {
      simulateWsEvent({
        event: "meeting_ended",
        meeting_id: 1,
        timestamp: Date.now(),
        payload: {},
      });
    });

    // Wait for the ended meeting view
    await waitFor(() => {
      expect(screen.getByText("Meeting Ended")).toBeInTheDocument();
    });

    // Vote results should still be visible
    await waitFor(() => {
      expect(screen.getByText("Floor Color")).toBeInTheDocument();
    });

    // The "preserved" message should appear
    await waitFor(() => {
      expect(screen.getByText(/Results Preserved/)).toBeInTheDocument();
    });
  });

  it("4. no active meeting, sessionStorage has endedMeetingId → shows Meeting Ended with vote results", async () => {
    // Pre-populate sessionStorage
    sessionStorage.setItem("smartdesk.display.endedMeetingId", "1");

    // First render: no active meeting, but endedMeetingId is restored from storage
    mockFetch
      .mockResolvedValueOnce(okResponse(null)) // fetchActiveMeeting → null
      .mockResolvedValueOnce(okResponse([{ id: 10, meeting_id: 1, title: "Floor Color", options: ["Blue", "Red"], status: "closed", is_anonymous: false }])) // fetchVotesForMeeting(1)
      .mockResolvedValueOnce(okResponse([])) // fetchAgendas(1)
      .mockResolvedValueOnce(okResponse(closedVoteStats())); // fetchVoteStatistics(10)

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Meeting Ended")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("Floor Color")).toBeInTheDocument();
      expect(screen.getByText("Blue")).toBeInTheDocument();
      expect(screen.getByText("Red")).toBeInTheDocument();
    });
  });

  it("5. endedMeetingId exists but new active meeting appears → shows new meeting, clears ended meeting", async () => {
    // First: no active meeting, restore ended meeting from storage
    sessionStorage.setItem("smartdesk.display.endedMeetingId", "1");

    mockFetch
      .mockResolvedValueOnce(okResponse(null)) // fetchActiveMeeting → null (first load)
      .mockResolvedValueOnce(okResponse([{ id: 10, meeting_id: 1, title: "Floor Color", options: ["Blue", "Red"], status: "closed", is_anonymous: false }])) // fetchVotesForMeeting(1)
      .mockResolvedValueOnce(okResponse([])) // fetchAgendas(1)
      .mockResolvedValueOnce(okResponse(closedVoteStats())); // fetchVoteStatistics(10)

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Meeting Ended")).toBeInTheDocument();
    });

    // Now simulate new active meeting appearing (e.g., user clicked Refresh)
    // Clear previous mocks and set up new ones
    mockFetch
      .mockReset()
      .mockResolvedValueOnce(okResponse(activeMeeting({ id: 2, title: "New Strategy Meeting" }))) // fetchActiveMeeting returns new meeting
      .mockResolvedValueOnce(okResponse(null)) // fetchActiveVote → null
      .mockResolvedValueOnce(okResponse([{ id: 20, meeting_id: 2, title: "New Vote", options: ["Yes", "No"], status: "closed", is_anonymous: false }])) // fetchVotesForMeeting(2)
      .mockResolvedValueOnce(okResponse([])) // fetchAgendas(2)
      .mockResolvedValueOnce(okResponse({ // fetchVoteStatistics(20)
        vote_id: 20,
        title: "New Vote",
        is_anonymous: false,
        status: "closed",
        total_votes: 3,
        results: [
          { option: "Yes", count: 3, attendee_ids: [1, 2, 3] },
        ],
      }));

    // Click Refresh
    await act(async () => {
      screen.getByText("Refresh").click();
    });

    await waitFor(() => {
      expect(screen.getByText("New Strategy Meeting")).toBeInTheDocument();
    });

    // Ended meeting state should be gone
    expect(screen.queryByText(/会议已结束/)).not.toBeInTheDocument();
    expect(screen.queryByText("Floor Color")).not.toBeInTheDocument();

    // New meeting votes should show
    await waitFor(() => {
      expect(screen.getByText("New Vote")).toBeInTheDocument();
    });

    // sessionStorage should be cleared
    expect(sessionStorage.getItem("smartdesk.display.endedMeetingId")).toBeNull();
  });

  it("6. meeting ended with open vote → re-fetches and shows closed vote result", async () => {
    // First render: active meeting with open vote
    // Call order inside load():
    //   1. fetchActiveMeeting
    //   Promise.all:
    //     2. fetchActiveVote
    //     3. fetchVotesForMeeting (inside fetchVoteResultsForMeeting)
    //   4. fetchVoteStatistics(11) for list vote
    //   5. fetchVoteStatistics(11) for active vote
    mockFetch
      .mockResolvedValueOnce(okResponse(activeMeeting({ id: 1, title: "Board Meeting" }))) // 1
      .mockResolvedValueOnce(okResponse({ id: 11, meeting_id: 1, title: "Lunch Choice", options: ["Pizza", "Salad"], status: "open", is_anonymous: false })) // 2
      .mockResolvedValueOnce(okResponse([{ id: 11, meeting_id: 1, title: "Lunch Choice", options: ["Pizza", "Salad"], status: "open", is_anonymous: false }])) // 3: fetchVotesForMeeting
      .mockResolvedValueOnce(okResponse([])) // 4: fetchAgendas(1)
      .mockResolvedValueOnce(okResponse(openVoteStats())) // 5: fetchVoteStatistics(11) from fetchVoteResultsForMeeting
      .mockResolvedValueOnce(okResponse(openVoteStats())); // 6: fetchVoteStatistics(11) for activeVote

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("Lunch Choice")).toBeInTheDocument();
      expect(screen.getByText("Vote In Progress")).toBeInTheDocument();
    });

    // Simulate meeting_ended WS event — backend closes the open vote
    // Triggering load() again:
    //   1. fetchActiveMeeting → null
    //   2. fetchVotesForMeeting(endedMeetingId=1)
    //   3. fetchAgendas(1)
    //   4. fetchVoteStatistics(11)
    mockFetch
      .mockReset()
      .mockResolvedValueOnce(okResponse(null)) // 1: fetchActiveMeeting → null
      .mockResolvedValueOnce(okResponse([{ id: 11, meeting_id: 1, title: "Lunch Choice", options: ["Pizza", "Salad"], status: "closed", is_anonymous: false }])) // 2: fetchVotesForMeeting
      .mockResolvedValueOnce(okResponse([])) // 3: fetchAgendas(1)
      .mockResolvedValueOnce(okResponse({ // 4: fetchVoteStatistics(11)
        vote_id: 11,
        title: "Lunch Choice",
        is_anonymous: false,
        status: "closed",
        total_votes: 2,
        results: [
          { option: "Pizza", count: 1, attendee_ids: [1] },
          { option: "Salad", count: 1, attendee_ids: [2] },
        ],
      }));

    simulateWsEvent({
      event: "meeting_ended",
      meeting_id: 1,
      timestamp: Date.now(),
      payload: {},
    });

    await waitFor(() => {
      expect(screen.getByText("Meeting Ended")).toBeInTheDocument();
    });

    // Vote should now show "Vote Result" (closed) instead of "Vote In Progress"
    await waitFor(() => {
      expect(screen.getByText("Vote Result")).toBeInTheDocument();
    });

    // Vote results should still be visible
    expect(screen.getByText("Pizza")).toBeInTheDocument();
    expect(screen.getByText("Salad")).toBeInTheDocument();
  });
});

// ── Task 6 — Display Polling Tests ────────────────────────────────────────

describe("DisplayView — Task 6 polling for active meeting", () => {
  // Override the polling interval to 100ms for fast tests
  let originalInterval: number;

  beforeAll(async () => {
    const mod = await import("../components/DisplayView");
    originalInterval = mod.DISPLAY_POLL_INTERVAL_MS;
    mod.__setPollInterval(100);
  });

  afterAll(async () => {
    const mod = await import("../components/DisplayView");
    mod.__setPollInterval(originalInterval);
  });

  /**
   * Helper: set up a mock that returns null for active meeting but ok(null)
   * for all other unmatched calls so polling doesn't crash.
   */
  function mockNoActiveMeeting() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      return okResponse(null);
    });
  }

  it("polls fetchActiveMeeting when in waiting state (no meeting, no endedMeetingId)", async () => {
    mockNoActiveMeeting();

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Waiting for Meeting")).toBeInTheDocument();
    });

    const callsAfterRender = mockFetch.mock.calls.length;

    // Wait for polling interval to fire
    await new Promise((r) => setTimeout(r, 350));

    // After polling, fetchActiveMeeting should have been called again
    expect(mockFetch.mock.calls.length).toBeGreaterThan(callsAfterRender);
    const meetingCalls = mockFetch.mock.calls.filter(
      (c: unknown[]) => c[0] === "/api/meetings/active"
    );
    expect(meetingCalls.length).toBeGreaterThan(1);
  });

  it("stops polling and shows meeting when active meeting found via poll", async () => {
    // First call returns null (initial load)
    mockNoActiveMeeting();

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Waiting for Meeting")).toBeInTheDocument();
    });

    // After initial render, switch mock to return active meeting.
    // Poll callback calls fetchActiveMeeting() → active meeting, then calls load()
    // which calls fetchActiveMeeting() again and subsequent endpoints.
    mockFetch.mockReset();
    mockFetch
      .mockImplementation((url: string) => {
        if (url === "/api/meetings/active") return okResponse(activeMeeting({ id: 2, title: "New Meeting From Poll" }));
        if (url === "/api/votes/active") return okResponse(null);
        if (url.includes("/api/votes?meeting_id=")) return okResponse([]);
        if (url.includes("/api/meetings/") && url.endsWith("/agendas")) return okResponse([]);
        return okResponse(null);
      });

    // Wait for polling to trigger + re-render
    await new Promise((r) => setTimeout(r, 500));

    // Should now show the new meeting
    await waitFor(() => {
      expect(screen.getByText("New Meeting From Poll")).toBeInTheDocument();
    });

    // "Waiting for Meeting" should be gone
    expect(screen.queryByText("Waiting for Meeting")).not.toBeInTheDocument();
  });

  it("polls and finds new active meeting when in ended meeting result view", async () => {
    sessionStorage.setItem("smartdesk.display.endedMeetingId", "1");

    mockFetch
      .mockResolvedValueOnce(okResponse(null))  // fetchActiveMeeting → null
      .mockResolvedValueOnce(okResponse([{ id: 10, meeting_id: 1, title: "Floor", options: ["Blue", "Red"], status: "closed", is_anonymous: false }])) // fetchVotesForMeeting
      .mockResolvedValueOnce(okResponse([])) // fetchAgendas(1)
      .mockResolvedValueOnce(okResponse(closedVoteStats())); // fetchVoteStatistics(10)

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Meeting Ended")).toBeInTheDocument();
    });

    // Now the ended meeting view is shown. The polling should have started.
    // Switch mock to return a new active meeting.
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(activeMeeting({ id: 3, title: "New Meeting After End" }));
      if (url === "/api/votes/active") return okResponse(null);
      if (url.includes("/api/votes?meeting_id=")) return okResponse([]);
      if (url.includes("/api/meetings/") && url.endsWith("/agendas")) return okResponse([]);
      return okResponse(null);
    });

    // Wait for polling to trigger and load() to re-render
    await new Promise((r) => setTimeout(r, 500));

    // Should now show the new meeting — ended meeting view is replaced
    await waitFor(() => {
      expect(screen.getByText("New Meeting After End")).toBeInTheDocument();
    });

    // Ended meeting indicators should be gone
    expect(screen.queryByText(/会议已结束/)).not.toBeInTheDocument();
    // h1 should show the new meeting title, not "Waiting for Meeting"
    expect(screen.queryByText("Waiting for Meeting")).not.toBeInTheDocument();

    sessionStorage.removeItem("smartdesk.display.endedMeetingId");
  });

  it("keeps ended meeting results and does not overwrite when poll returns null", async () => {
    sessionStorage.setItem("smartdesk.display.endedMeetingId", "1");

    // Use mockImplementation so polling calls also get null for active meeting
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") return okResponse(null);
      if (url === "/api/votes?meeting_id=1") return okResponse([{ id: 10, meeting_id: 1, title: "Floor", options: ["Blue", "Red"], status: "closed", is_anonymous: false }]);
      if (url === "/api/votes/10/statistics") return okResponse(closedVoteStats());
      if (url.includes("/api/meetings/") && url.endsWith("/agendas")) return okResponse([]);
      return okResponse(null);
    });

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Meeting Ended")).toBeInTheDocument();
    });

    // Polling should not overwrite the ended meeting view when no new meeting
    expect(screen.getByText(/Results Preserved/)).toBeInTheDocument();
    expect(screen.queryByText("Waiting for Meeting")).not.toBeInTheDocument();

    sessionStorage.removeItem("smartdesk.display.endedMeetingId");
  });

  it("cleans up timer on unmount", async () => {
    mockNoActiveMeeting();

    const { unmount } = renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Waiting for Meeting")).toBeInTheDocument();
    });

    const callsBefore = mockFetch.mock.calls.length;

    // Unmount — should clean up timer
    unmount();

    // Wait — no more calls since component is unmounted
    await new Promise((r) => setTimeout(r, 350));

    // No additional calls after unmount
    expect(mockFetch.mock.calls.length).toBe(callsBefore);
  });
});

// ── Task 4 Button Rules ───────────────────────────────────────────────────

describe("DisplayView — Task 4 button rules", () => {
  it("only shows Refresh button, no write operation buttons", async () => {
    mockFetch
      .mockResolvedValueOnce(okResponse(activeMeeting()))
      .mockResolvedValueOnce(okResponse(null))
      .mockResolvedValueOnce(okResponse([{ id: 10, meeting_id: 1, title: "Floor Color", options: ["Blue", "Red"], status: "closed", is_anonymous: false }]))
      .mockResolvedValueOnce(okResponse(closedVoteStats()));

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument();
    });

    // Only Refresh button should exist
    const refreshBtn = screen.getByText("Refresh");
    expect(refreshBtn).toBeInTheDocument();
    expect(refreshBtn).not.toBeDisabled();

    // No write operation buttons should appear
    expect(screen.queryByText("Create Vote")).not.toBeInTheDocument();
    expect(screen.queryByText("Close Vote")).not.toBeInTheDocument();
    expect(screen.queryByText("End Meeting")).not.toBeInTheDocument();
    expect(screen.queryByText("Start Meeting")).not.toBeInTheDocument();
    expect(screen.queryByText("Set Speaker")).not.toBeInTheDocument();
    expect(screen.queryByText("Clear Speaker")).not.toBeInTheDocument();
    expect(screen.queryByText("Create Pending Meeting")).not.toBeInTheDocument();
    expect(screen.queryByText("Add Attendee")).not.toBeInTheDocument();
    expect(screen.queryByText("Add Agenda")).not.toBeInTheDocument();
  });
});

// ── Phase 3: Display Agenda Tests ────────────────────────────────────────────

describe("DisplayView — agenda progress (Phase 3)", () => {
  function activeMeetingWithAgendas(agendas: unknown[]) {
    mockFetch
      .mockResolvedValueOnce(okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" })) // fetchActiveMeeting
      .mockResolvedValueOnce(okResponse(null)) // fetchActiveVote
      .mockResolvedValueOnce(okResponse([])) // fetchVotesForMeeting
      .mockResolvedValueOnce(okResponse(agendas)); // fetchAgendas
  }

  it("shows current agenda title and progress when meeting is active", async () => {
    activeMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "Budget Review", sort_order: 2, status: "active", started_at: null, completed_at: null, skipped_at: null },
      { id: 3, meeting_id: 1, title: "Q&A", sort_order: 3, status: "pending", started_at: null, completed_at: null, skipped_at: null },
    ]);

    renderDisplay();

    await waitFor(() => {
      const titles = screen.getAllByText("Budget Review");
      expect(titles.length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText("当前议题")).toBeInTheDocument();
    expect(screen.getByText("CURRENT TOPIC")).toBeInTheDocument();
  });

  it("shows '所有议题已处理' / ALL TOPICS PROCESSED when all agendas are done", async () => {
    activeMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "Budget", sort_order: 2, status: "skipped", started_at: null, completed_at: null, skipped_at: null },
    ]);

    renderDisplay();

    await waitFor(() => {
      const els = screen.getAllByText("所有议题已处理");
      expect(els.length).toBeGreaterThanOrEqual(1);
    });
    const allDoneEls = screen.getAllByText("ALL TOPICS PROCESSED");
    expect(allDoneEls.length).toBeGreaterThanOrEqual(1);
  });

  it("shows '暂无当前议题' / NO ACTIVE TOPIC when no active agenda but pending remain", async () => {
    activeMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "Budget", sort_order: 2, status: "pending", started_at: null, completed_at: null, skipped_at: null },
    ]);

    renderDisplay();

    await waitFor(() => {
      const els = screen.getAllByText("暂无当前议题");
      expect(els.length).toBeGreaterThanOrEqual(1);
    });
    const noActiveEls = screen.getAllByText("NO ACTIVE TOPIC");
    expect(noActiveEls.length).toBeGreaterThanOrEqual(1);
  });

  it("shows correct progress number (e.g. '2 / 5')", async () => {
    activeMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "A", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "B", sort_order: 2, status: "active", started_at: null, completed_at: null, skipped_at: null },
      { id: 3, meeting_id: 1, title: "C", sort_order: 3, status: "pending", started_at: null, completed_at: null, skipped_at: null },
    ]);

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("2 / 3")).toBeInTheDocument();
    });
  });

  it("shows bilingual agenda statuses in the vertical timeline", async () => {
    activeMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "A", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "B", sort_order: 2, status: "active", started_at: null, completed_at: null, skipped_at: null },
      { id: 3, meeting_id: 1, title: "C", sort_order: 3, status: "skipped", started_at: null, completed_at: null, skipped_at: null },
      { id: 4, meeting_id: 1, title: "D", sort_order: 4, status: "pending", started_at: null, completed_at: null, skipped_at: null },
    ]);

    renderDisplay();

    await waitFor(() => {
      const titles = screen.getAllByText("B");
      expect(titles.length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText(/已完成 \/ Completed/)).toBeInTheDocument();
    expect(screen.getByText(/进行中 \/ Active/)).toBeInTheDocument();
    expect(screen.getByText(/已跳过 \/ Skipped/)).toBeInTheDocument();
    expect(screen.getByText(/待处理 \/ Pending/)).toBeInTheDocument();
    expect(screen.queryByText("Done")).not.toBeInTheDocument();
    expect(screen.queryByText("Skip")).not.toBeInTheDocument();
  });

  it("uses the full-screen agenda and vote columns", async () => {
    activeMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening", sort_order: 1, status: "active", started_at: null, completed_at: null, skipped_at: null },
    ]);

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByTestId("display-dashboard-grid")).toBeInTheDocument();
    });

    expect(screen.getByTestId("display-dashboard-grid")).toHaveClass("lg:grid-cols-12");
    expect(screen.getByTestId("display-agenda-panel")).toHaveClass("lg:col-span-4");
    expect(screen.getByTestId("display-vote-panel")).toHaveClass("lg:col-span-8");
  });

  it("fetches ended meeting agendas when endedMeetingId is set", async () => {
    sessionStorage.setItem("smartdesk.display.endedMeetingId", "5");

    mockFetch
      .mockResolvedValueOnce(okResponse(null)) // fetchActiveMeeting → null
      .mockResolvedValueOnce(okResponse([])) // fetchVotesForMeeting(5)
      .mockResolvedValueOnce(okResponse([ // fetchAgendas(5)
        { id: 10, meeting_id: 5, title: "Closed Topic", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      ]));

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Meeting Ended")).toBeInTheDocument();
    });

    // Ended meeting agendas should still be displayed
    await waitFor(() => {
      expect(screen.getByText("所有议题已处理")).toBeInTheDocument();
    });

    sessionStorage.removeItem("smartdesk.display.endedMeetingId");
  });

  it("only shows Refresh button, no agenda control buttons", async () => {
    activeMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening", sort_order: 1, status: "active", started_at: null, completed_at: null, skipped_at: null },
    ]);

    renderDisplay();

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument();
    });

    // No agenda control buttons
    expect(screen.queryByText("Set Current")).not.toBeInTheDocument();
    expect(screen.queryByText("Advance")).not.toBeInTheDocument();
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
    expect(screen.queryByText("Skip")).not.toBeInTheDocument();
    expect(screen.queryByText("Add Agenda")).not.toBeInTheDocument();
  });

  it("re-fetches on agenda_updated WS event", async () => {
    let agendasCallCount = 0;

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/votes/active") return okResponse(null);
      if (url.includes("/api/votes?meeting_id=")) return okResponse([]);
      if (url.includes("/api/meetings/1/agendas")) {
        agendasCallCount++;
        return okResponse([{ id: 1, meeting_id: 1, title: "Opening", sort_order: 1, status: "active", started_at: null, completed_at: null, skipped_at: null }]);
      }
      return okResponse(null);
    });

    renderDisplay();

    await waitFor(() => {
      const titles = screen.getAllByText("Opening");
      expect(titles.length).toBeGreaterThanOrEqual(1);
    });

    const initialCalls = agendasCallCount;

    // Simulate agenda_updated event
    await act(async () => {
      simulateWsEvent({
        event: "agenda_updated",
        meeting_id: 1,
        timestamp: Date.now(),
        payload: {},
      });
      await new Promise((r) => setTimeout(r, 100));
    });

    // Should have re-fetched agendas
    expect(agendasCallCount).toBeGreaterThan(initialCalls);
  });
});
