/// <reference types="vitest" />
import {
  clearSpeakerSeat,
  createAgenda,
  createAttendee,
  createMeeting,
  deleteAgenda,
  deleteAttendee,
  endMeeting,
  fetchVoteResultsForMeeting,
  fetchVotesForMeeting,
  setSpeakerSeat,
  startMeeting,
} from "../api/resources";

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function okResponse(data: unknown = null) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, message: "OK", data }),
  };
}

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockResolvedValue(okResponse({}));
});

describe("control resource API wrappers", () => {
  it("creates, starts, and ends meetings", async () => {
    await createMeeting("Planning", "Room A");
    await startMeeting(3);
    await endMeeting(3);

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      "/api/meetings",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ title: "Planning", description: "Room A" }),
      }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      "/api/meetings/3/start",
      expect.objectContaining({ method: "POST" }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      3,
      "/api/meetings/3/end",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("sets and clears speaker seat", async () => {
    await setSpeakerSeat(2);
    await clearSpeakerSeat();

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      "/api/seats/speaker",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ seat_id: 2 }),
      }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      "/api/seats/speaker",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("creates and deletes attendees and agenda items", async () => {
    await createAttendee(7, "Alice", "CEO");
    await deleteAttendee(7, 11);
    await createAgenda(7, "Opening", 1);
    await deleteAgenda(7, 22);

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      "/api/meetings/7/attendees",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "Alice", title: "CEO" }),
      }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      "/api/meetings/7/attendees/11",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      3,
      "/api/meetings/7/agendas",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ title: "Opening", sort_order: 1 }),
      }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      4,
      "/api/meetings/7/agendas/22",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("fetches meeting votes and vote results", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/votes?meeting_id=7") {
        return okResponse([
          {
            id: 11,
            meeting_id: 7,
            title: "Closed Vote",
            options: ["Yes", "No"],
            status: "closed",
            is_anonymous: false,
          },
        ]);
      }
      if (url === "/api/votes/11/statistics") {
        return okResponse({
          vote_id: 11,
          title: "Closed Vote",
          is_anonymous: false,
          status: "closed",
          total_votes: 2,
          results: [
            { option: "Yes", count: 2, attendee_ids: [1, 2] },
            { option: "No", count: 0, attendee_ids: [] },
          ],
        });
      }
      return okResponse(null);
    });

    const votes = await fetchVotesForMeeting(7);
    const results = await fetchVoteResultsForMeeting(7);

    expect(votes).toHaveLength(1);
    expect(votes[0].status).toBe("closed");
    expect(results).toHaveLength(1);
    expect(results[0].total_votes).toBe(2);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/votes?meeting_id=7",
      expect.objectContaining({ method: "GET" }),
    );
  });
});
