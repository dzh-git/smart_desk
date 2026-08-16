// ─── Unified HTTP API Client ──────────────────────────────────────────────
// BASE_URL is relative by default (Vite dev proxy / same-origin backend). On a
// seat terminal serving the frontend locally, app-config.js sets apiBase to the
// central host so requests reach the backend. All methods unwrap ApiResponse<T>
// and throw typed errors on failure.

import type { ApiResponse } from "./types";
import { apiBase } from "../app-config";

const BASE_URL = apiBase() + "/api";

// ── Error Types ──────────────────────────────────────────────────────────

/**
 * Thrown when the server responds with a non-2xx HTTP status or a
 * business-level error (success: false in the response body).
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number,
    public readonly errorCode?: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Thrown when the request itself fails (network down, DNS failure, CORS, etc.).
 */
export class NetworkError extends Error {
  public readonly originalError: unknown;

  constructor(cause: unknown) {
    super("Network error: unable to reach the server");
    this.name = "NetworkError";
    this.originalError = cause;
  }
}

// ── Core Request Function ────────────────────────────────────────────────

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });
  } catch (err) {
    throw new NetworkError(err);
  }

  // ── Handle HTTP-level errors (non-2xx) ──────────────────────────────
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = await response.json();
      // FastAPI returns { detail: "..." } on validation errors
      detail = body.detail ?? body.message ?? response.statusText;
    } catch {
      detail = response.statusText;
    }
    throw new ApiError(detail ?? "Unknown error", response.status, undefined);
  }

  // ── Handle business-level errors (success: false) ────────────────────
  let body: ApiResponse<T>;
  try {
    body = (await response.json()) as ApiResponse<T>;
  } catch {
    throw new ApiError("Invalid JSON response", response.status);
  }

  if (!body.success) {
    throw new ApiError(
      body.message ?? "Unknown business error",
      response.status,
      body.error_code,
    );
  }

  // `data` is guaranteed non-null when success is true per API contract
  return body.data as T;
}

// ── Convenience Methods ──────────────────────────────────────────────────

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

/**
 * Raw GET — fetches the path and returns the full JSON body as T WITHOUT
 * unwrapping an {success, data} envelope.  Use this for endpoints whose
 * FastAPI handler returns a Pydantic model directly (e.g.
 * GET /api/host-display/status).
 *
 * Throws ApiError for non-2xx HTTP statuses and NetworkError for
 * transport failures — exactly the same as apiGet.  The only difference
 * is that response.json() is returned as-is.
 */
export async function apiGetRaw<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    throw new NetworkError(err);
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = await response.json();
      detail = body.detail ?? body.message ?? response.statusText;
    } catch {
      detail = response.statusText;
    }
    throw new ApiError(detail ?? "Unknown error", response.status, undefined);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("Invalid JSON response", response.status);
  }
}

export function apiPost<T>(path: string, data?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: data !== undefined ? JSON.stringify(data) : undefined,
  });
}

export function apiPatch<T>(path: string, data?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    body: data !== undefined ? JSON.stringify(data) : undefined,
  });
}

export function apiPut<T>(path: string, data?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    body: data !== undefined ? JSON.stringify(data) : undefined,
  });
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

// Re-export for advanced usage
export { request as apiRequest };
