import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiGet, apiPost, ApiError, NetworkError } from "../client";

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockReset();
});

describe("apiGet", () => {
  it("returns data on successful response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        message: "OK",
        data: { id: 1, title: "Board Meeting" },
      }),
    });

    const result = await apiGet<{ id: number; title: string }>("/meetings/1");
    expect(result).toEqual({ id: 1, title: "Board Meeting" });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/meetings/1",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("throws ApiError on business error response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: false,
        message: "Meeting not found",
        data: null,
        error_code: "MEETING_NOT_FOUND",
      }),
    });

    const err = await apiGet("/meetings/999").catch((e) => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("Meeting not found");
    expect(err.errorCode).toBe("MEETING_NOT_FOUND");
    expect(err.statusCode).toBe(200);
  });

  it("throws ApiError on HTTP non-success (404)", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "MEETING_NOT_FOUND" }),
    });

    const err = await apiGet("/meetings/999").catch((e) => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.statusCode).toBe(404);
    expect(err.message).toContain("MEETING_NOT_FOUND");
  });

  it("throws ApiError on HTTP 500 with non-JSON body", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => {
        throw new Error("not json");
      },
    });

    const err = await apiGet("/meetings").catch((e) => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.statusCode).toBe(500);
    expect(err.message).toBe("Internal Server Error");
  });

  it("throws NetworkError when fetch fails", async () => {
    mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const err = await apiGet("/meetings").catch((e) => e) as ApiError;
    expect(err).toBeInstanceOf(NetworkError);
    expect(err.message).toContain("Network error");
  });

  it("rejects with null JSON body as T", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        message: "No active meeting",
        data: null,
      }),
    });

    const result = await apiGet<null>("/meetings/active");
    expect(result).toBeNull();
  });
});

describe("apiPost", () => {
  it("sends JSON body and returns data", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({
        success: true,
        message: "Created",
        data: { id: 1 },
      }),
    });

    const result = await apiPost("/meetings", {
      title: "Test",
      description: "Desc",
    });
    expect(result).toEqual({ id: 1 });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/meetings",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ title: "Test", description: "Desc" }),
      }),
    );
  });

  it("sends POST without body when data is undefined", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ success: true, message: "OK", data: null }),
    });

    await apiPost("/seats/speaker");
    const callArgs = mockFetch.mock.calls[0][1];
    expect(callArgs.body).toBeUndefined();
  });
});
