import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  fetchActiveMeeting,
  fetchSeats,
  fetchSpeakerSeat,
  fetchActiveVote,
  fetchVoteStatistics,
  fetchAgendas,
  fetchAttendees,
  fetchServiceCalls,
  fetchTranslations,
} from "../resources";

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function mockResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      success: true,
      message: "OK",
      data,
    }),
  };
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe("fetchActiveMeeting", () => {
  it("calls /api/meetings/active and returns meeting data", async () => {
    const meeting = {
      id: 1,
      title: "Board Meeting",
      status: "active",
    };
    mockFetch.mockResolvedValueOnce(mockResponse(meeting));

    const result = await fetchActiveMeeting();
    expect(result).toEqual(meeting);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/meetings/active",
      expect.any(Object),
    );
  });

  it("returns null when no active meeting exists", async () => {
    mockFetch.mockResolvedValueOnce(mockResponse(null));

    const result = await fetchActiveMeeting();
    expect(result).toBeNull();
  });
});

describe("fetchSeats", () => {
  it("calls /api/seats", async () => {
    const seats: unknown[] = [];
    mockFetch.mockResolvedValueOnce(mockResponse(seats));

    await fetchSeats();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/seats",
      expect.any(Object),
    );
  });
});

describe("fetchSpeakerSeat", () => {
  it("calls /api/seats/speaker", async () => {
    mockFetch.mockResolvedValueOnce(mockResponse({ seat_id: null }));

    const result = await fetchSpeakerSeat();
    expect(result).toEqual({ seat_id: null });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/seats/speaker",
      expect.any(Object),
    );
  });
});

describe("fetchActiveVote", () => {
  it("calls /api/votes/active and returns vote or null", async () => {
    mockFetch.mockResolvedValueOnce(mockResponse(null));
    const result = await fetchActiveVote();
    expect(result).toBeNull();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/votes/active",
      expect.any(Object),
    );
  });
});

describe("fetchVoteStatistics", () => {
  it("calls /api/votes/{id}/statistics", async () => {
    const stats = {
      vote_id: 1,
      title: "Test Vote",
      is_anonymous: false,
      status: "open",
      total_votes: 5,
      results: [{ option: "Yes", count: 3, attendee_ids: null }],
    };
    mockFetch.mockResolvedValueOnce(mockResponse(stats));

    const result = await fetchVoteStatistics(1);
    expect(result).toEqual(stats);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/votes/1/statistics",
      expect.any(Object),
    );
  });
});

describe("fetchAgendas", () => {
  it("calls /api/meetings/{id}/agendas", async () => {
    mockFetch.mockResolvedValueOnce(mockResponse([]));
    await fetchAgendas(5);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/meetings/5/agendas",
      expect.any(Object),
    );
  });
});

describe("fetchAttendees", () => {
  it("calls /api/meetings/{id}/attendees", async () => {
    mockFetch.mockResolvedValueOnce(mockResponse([]));
    await fetchAttendees(5);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/meetings/5/attendees",
      expect.any(Object),
    );
  });
});

describe("fetchServiceCalls", () => {
  it("calls /api/service-calls with meeting_id query param", async () => {
    mockFetch.mockResolvedValueOnce(mockResponse([]));
    await fetchServiceCalls(3);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/service-calls?meeting_id=3",
      expect.any(Object),
    );
  });
});

describe("fetchTranslations", () => {
  it("calls /api/translations with meeting_id query param", async () => {
    mockFetch.mockResolvedValueOnce(
      mockResponse({ meeting_id: 2, entries: [] }),
    );
    const result = await fetchTranslations(2);
    expect(result).toEqual({ meeting_id: 2, entries: [] });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/translations?meeting_id=2",
      expect.any(Object),
    );
  });
});
