import type { ReactElement } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render as rtlRender, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SeatTablet } from "../components/SeatTablet";

// ── Router-wrapped render helper ─────────────────────────────────────────────
// SeatTablet now uses useNavigate() for the "Shared Screen" entry button,
// so all tests need a Router context.  Wrap with MemoryRouter, keeping the
// same API so existing tests require no individual changes.
function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter initialEntries={["/seat/1"]}>{ui}</MemoryRouter>,
  );
}

// ── Mock isDemoControlsEnabled ───────────────────────────────────────────────
let mockDemoControls = false;

vi.mock("../components/shared", async () => {
  const actual = await vi.importActual("../components/shared");
  return {
    ...actual,
    isDemoControlsEnabled: () => mockDemoControls,
  };
});

// ── Mock WebSocket (multi-instance tracking) ─────────────────────────────────
// Tracks ALL WebSocket instances in an array so we can interact with each
// WS connection (meeting broadcast + speech uplink) independently.

const wsInstances: MultiMockWebSocket[] = [];

class MultiMockWebSocket {
  url: string;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  sentData: (string | ArrayBufferLike)[] = [];

  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url: string) {
    this.url = url;
    wsInstances.push(this);

    // Defer onopen so the real handler is assigned first.
    // Wrap in act() to prevent React state update warnings.
    Promise.resolve().then(() => {
      this.readyState = 1;
      if (this.onopen) {
        act(() => {
          this.onopen!();
        });
      }
    });
  }

  send(data: string | ArrayBufferLike): void {
    this.sentData.push(data);
  }

  close(): void {
    this.readyState = 3;
    const idx = wsInstances.indexOf(this);
    if (idx >= 0) wsInstances.splice(idx, 1);
    if (this.onclose) {
      act(() => {
        this.onclose!();
      });
    }
  }
}

// ---- Helper: find WS by URL pattern ----

function findMeetingWs(): MultiMockWebSocket | null {
  return (
    wsInstances.find((i) => i.url.includes("/ws/") && !i.url.includes("/ws/speech/")) ?? null
  );
}

function findSpeechWs(): MultiMockWebSocket | null {
  return wsInstances.find((i) => i.url.includes("/ws/speech/")) ?? null;
}

/** Helper: get all speech WS sent messages filtered by JSON type. */
function speechWsSentMessages(): string[] {
  const ws = findSpeechWs();
  if (!ws) return [];
  return ws.sentData.filter((d): d is string => typeof d === "string");
}

/** Send a JSON message into the meeting WS. */
async function triggerWsEvent(
  event: string,
  meetingId: number,
  payload: Record<string, unknown> = {},
) {
  const ws = findMeetingWs();
  if (ws?.onmessage) {
    await act(async () => {
      ws.onmessage!({
        data: JSON.stringify({
          event,
          meeting_id: meetingId,
          timestamp: Math.floor(Date.now() / 1000),
          payload,
        }),
      });
    });
  }
}

/** Disconnect the meeting WS. */
function wsDisconnect() {
  const ws = findMeetingWs();
  if (ws) ws.close();
}

beforeEach(() => {
  // Clear tracked instances from previous tests
  wsInstances.length = 0;
  (globalThis as unknown as Record<string, unknown>).WebSocket = MultiMockWebSocket as unknown as typeof WebSocket;
  Reflect.deleteProperty(window, "SmartDeskNative");
  mockDemoControls = false;
});

afterEach(() => {
  Reflect.deleteProperty(window, "SmartDeskNative");
  mockDemoControls = false;
  vi.restoreAllMocks();
});

// ── Mock fetch ──────────────────────────────────────────────────────────────

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function okResponse(data: unknown) {
  const normalized = Array.isArray(data)
    ? data.map((item) => {
        if (
          item &&
          typeof item === "object" &&
          "meeting_id" in item &&
          "checked_in" in item &&
          !("assigned_seat_id" in item)
        ) {
          const attendee = item as Record<string, unknown>;
          return {
            ...attendee,
            assigned_seat_id: attendee.checked_in
              ? attendee.seat_id ?? null
              : null,
          };
        }
        return item;
      })
    : data;
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, message: "OK", data: normalized }),
  };
}

/** Create a generic active meeting + seats mock factory */
function createSeatMock(
  seatStatus: "vacant" | "occupied_unchecked" | "checked_in" = "vacant",
) {
  return (url: string) => {
    if (url === "/api/meetings/active") {
      return okResponse({
        id: 1,
        title: "Board Meeting",
        status: "active",
        started_at: "2026-01-01T10:00:00Z",
      });
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
      return okResponse([
        {
          id: 1,
          meeting_id: 1,
          person_id: "person_001",
          name: "Alice Wang",
          title: "CEO",
          assigned_seat_id: 1,
          seat_id: seatStatus === "checked_in" ? 1 : null,
          checked_in: seatStatus === "checked_in",
        },
      ]);
    }
    if (url === "/api/meetings/1/agendas") return okResponse([]);
    if (url.includes("/api/translations"))
      return okResponse({ meeting_id: 1, entries: [] });
    return okResponse(null);
  };
}

beforeEach(() => {
  mockFetch.mockReset();
});

// ── Existing Tests ──────────────────────────────────────────────────────────

describe("SeatTablet - loading state", () => {
  it("shows loading state initially", () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    expect(screen.getByText(/正在加载席位数据.*Loading seat data/)).toBeInTheDocument();
  });
});

describe("SeatTablet - error state", () => {
  it("shows error state with retry button", async () => {
    mockFetch.mockRejectedValue(new Error("API failure"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/正在重新连接会议系统.*Reconnecting/)).toBeInTheDocument();
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
      expect(screen.getByText(/等待会议开始.*Waiting for Meeting/)).toBeInTheDocument();
    });
  });

  it("detects a meeting started after more than one idle poll", async () => {
    vi.useFakeTimers();
    try {
      const active = createSeatMock("checked_in");
      let started = false;
      mockFetch.mockImplementation((url: string) =>
        url === "/api/meetings/active" && !started ? okResponse(null) : active(url),
      );
      render(<SeatTablet seatId={1} />);
      await act(async () => {});
      await act(async () => vi.advanceTimersByTimeAsync(5000));
      started = true;
      await act(async () => vi.advanceTimersByTimeAsync(5000));
      expect(screen.getByText("Board Meeting")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("SeatTablet - face gate", () => {
  it("hides meeting controls while the assigned seat is vacant", async () => {
    mockFetch.mockImplementation(createSeatMock("vacant"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("face-access-gate")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("seat-screen-entry")).not.toBeInTheDocument();
    expect(screen.queryByText(/模拟入座.*Occupy Seat \(Demo\)/)).not.toBeInTheDocument();
  });

  it("does not expose demo occupy controls at the gate", async () => {
    mockDemoControls = true;
    mockFetch.mockImplementation(createSeatMock("vacant"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("face-access-gate")).toBeInTheDocument();
    });
    expect(screen.queryByText(/模拟入座.*Occupy Seat \(Demo\)/)).not.toBeInTheDocument();
  });

  it("keeps occupied_unchecked seats behind the gate", async () => {
    mockFetch.mockImplementation(createSeatMock("occupied_unchecked"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("face-access-gate")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Confirm Check-in/)).not.toBeInTheDocument();
    expect(screen.queryByText(/模拟离座.*Vacate \(Demo\)/)).not.toBeInTheDocument();
  });

  it("does not expose demo vacate controls before check-in", async () => {
    mockDemoControls = true;
    mockFetch.mockImplementation(createSeatMock("occupied_unchecked"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("face-access-gate")).toBeInTheDocument();
    });
    expect(screen.queryByText(/模拟离座.*Vacate \(Demo\)/)).not.toBeInTheDocument();
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

describe("SeatTablet - Android identity check-in", () => {
  function installNativeBridge(
    overrides: Partial<Window["SmartDeskNative"]> = {},
    identityMode: "formal" | "debug" = "formal",
  ) {
    Object.defineProperty(window, "SmartDeskNative", {
      configurable: true,
      value: {
        getDeviceInfo: vi.fn(() =>
          JSON.stringify({
            schemaVersion: 1,
            eventId: "device-info-event-0001",
            type: "device_info",
            timestamp: 1_700_000_000_000,
            data: {
              deviceId: "tablet-seat-01",
              seatId: 1,
              serverUrl: "http://host:8000",
              frontendUrl: "http://host:5173",
              configured: true,
              maintenanceAccessAvailable: true,
              appVersion: "0.8.0",
              cameraReady: true,
              faceModelReady: true,
              microphoneReady: true,
              nativeLastError: null,
              identityMode,
            },
          }),
        ),
        getDeviceCredential: vi.fn(() =>
          JSON.stringify({
            schemaVersion: 1,
            eventId: "device-credential-event-0001",
            type: "device_credential",
            timestamp: 1_700_000_000_000,
            data: {
              deviceToken: "device-secret-token-00000001",
            },
          }),
        ),
        getIdentityStatus: vi.fn(() =>
          JSON.stringify({
            schemaVersion: 1,
            eventId: "identity-status-event-0001",
            type: "identity_status",
            timestamp: 1_700_000_000_000,
            data: { status: "IDLE" },
          }),
        ),
        getRegisteredFaces: vi.fn(() =>
          JSON.stringify({
            schemaVersion: 1,
            eventId: "registered-faces-event-0001",
            type: "registered_people",
            timestamp: 1_700_000_000_000,
            data: {
              personIds: ["person_001", "person_002"],
              count: 2,
            },
          }),
        ),
        startFaceVerification: vi.fn(() =>
          JSON.stringify({
            schemaVersion: 1,
            eventId: "verification-start-event-0001",
            type: "identity_status",
            timestamp: 1_700_000_000_000,
            data: { status: "VERIFYING" },
          }),
        ),
        beginMaintenanceHold: vi.fn(),
        cancelMaintenanceHold: vi.fn(),
        stopFaceVerification: vi.fn(),
        ...overrides,
      },
    });
  }

  it("places the maintenance hold control after status and time in the scrolling header", async () => {
    const beginMaintenanceHold = vi.fn();
    const cancelMaintenanceHold = vi.fn();
    installNativeBridge({
      beginMaintenanceHold,
      cancelMaintenanceHold,
    });
    mockFetch.mockImplementation(createSeatMock("vacant"));

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    const button = await screen.findByTestId("maintenance-access");
    const scrollContainer = screen.getByTestId("seat-page-scroll");
    expect(scrollContainer).toContainElement(button);
    expect(scrollContainer).toHaveClass("overflow-y-auto");
    expect(button.parentElement?.lastElementChild).toBe(button);

    fireEvent.pointerDown(button);
    await waitFor(() => expect(beginMaintenanceHold).toHaveBeenCalledTimes(1));
    fireEvent.pointerUp(button);
    await waitFor(() => expect(cancelMaintenanceHold).toHaveBeenCalledTimes(1));
  });

  it("automatically starts face verification while an active seat is vacant", async () => {
    const startFaceVerification = vi.fn();
    installNativeBridge({ startFaceVerification });
    mockFetch.mockImplementation(createSeatMock("vacant"));

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await screen.findByText("自动人脸入座");
    expect(screen.getByText("AUTOMATIC FACE CHECK-IN")).toBeInTheDocument();
    await waitFor(() =>
      expect(startFaceVerification).toHaveBeenCalledTimes(1),
    );
  });

  it("debug mode admits the assigned attendee without camera verification", async () => {
    const startFaceVerification = vi.fn();
    const syncFaceTemplates = vi.fn();
    installNativeBridge(
      { startFaceVerification, syncFaceTemplates },
      "debug",
    );
    let seatStatus: "vacant" | "checked_in" = "vacant";
    const debugCalls: Array<{ url: string; body: string | undefined }> = [];
    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (url === "/api/seats/1/debug-admit") {
        debugCalls.push({ url, body: options?.body as string | undefined });
        seatStatus = "checked_in";
        return okResponse({
          seat_id: 1,
          status: "checked_in",
          attendee_id: 1,
          updated_at: "2026-01-01T00:00:00Z",
        });
      }
      return createSeatMock(seatStatus)(url);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => expect(debugCalls).toHaveLength(1));
    await screen.findByText("DEBUG · 已跳过人脸验证");
    expect(JSON.parse(debugCalls[0].body ?? "{}")).toEqual({
      deviceId: "tablet-seat-01",
      deviceSeatId: 1,
    });
    expect(startFaceVerification).not.toHaveBeenCalled();
    expect(syncFaceTemplates).not.toHaveBeenCalled();
  });

  it("restarts automatic verification when the same attendee is reassigned", async () => {
    const startFaceVerification = vi.fn();
    installNativeBridge({ startFaceVerification });
    const baseMock = createSeatMock("vacant");
    let assigned = true;
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          {
            id: 1,
            meeting_id: 1,
            person_id: "person_001",
            name: "Alice Wang",
            title: "CEO",
            assigned_seat_id: assigned ? 1 : null,
            seat_id: null,
            checked_in: false,
          },
        ]);
      }
      return baseMock(url);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await waitFor(() =>
      expect(startFaceVerification).toHaveBeenCalledWith("person_001"),
    );

    assigned = false;
    await triggerWsEvent("seat_assignment_updated", 1, {
      seat_id: 1,
      attendee_id: 1,
      action: "cleared",
    });
    await screen.findByText(/等待主持人分配席位人员/);
    act(() => {
      window.dispatchEvent(
        new CustomEvent("smartdesk-native-event", {
          detail: {
            schemaVersion: 1,
            eventId: "assignment-cleared-event-0001",
            type: "identity_status",
            timestamp: 1_700_000_000_050,
            data: { status: "UNKNOWN" },
          },
        }),
      );
    });

    assigned = true;
    await triggerWsEvent("seat_assignment_updated", 1, {
      seat_id: 1,
      attendee_id: 1,
      action: "assigned",
    });

    await waitFor(() =>
      expect(startFaceVerification).toHaveBeenCalledTimes(2),
    );
    expect(startFaceVerification).toHaveBeenLastCalledWith("person_001");
  });

  it("requires an explicit retry after an unrecognized face", async () => {
    const startFaceVerification = vi.fn();
    installNativeBridge({ startFaceVerification });
    mockFetch.mockImplementation(createSeatMock("vacant"));

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await waitFor(() =>
      expect(startFaceVerification).toHaveBeenCalledTimes(1),
    );

    act(() => {
      window.dispatchEvent(
        new CustomEvent("smartdesk-native-event", {
          detail: {
            schemaVersion: 1,
            eventId: "unknown-event-0001",
            type: "identity_status",
            timestamp: 1_700_000_000_100,
            data: { status: "UNKNOWN", message: "No registered match" },
          },
        }),
      );
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    });
    expect(startFaceVerification).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText(/重新识别.*Retry Recognition/));
    await waitFor(() => expect(startFaceVerification).toHaveBeenCalledTimes(2));
  });

  it("does not retry a calibration configuration error", async () => {
    const startFaceVerification = vi.fn();
    installNativeBridge({ startFaceVerification });
    mockFetch.mockImplementation(createSeatMock("vacant"));

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await waitFor(() =>
      expect(startFaceVerification).toHaveBeenCalledTimes(1),
    );

    act(() => {
      window.dispatchEvent(
        new CustomEvent("smartdesk-native-event", {
          detail: {
            schemaVersion: 1,
            eventId: "calibration-event-0001",
            type: "identity_status",
            timestamp: 1_700_000_000_200,
            data: {
              status: "CALIBRATION_PENDING",
              message: "Face threshold calibration is incomplete",
            },
          },
        }),
      );
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 3_200));
    });
    expect(startFaceVerification).toHaveBeenCalledTimes(1);
  });

  it("stops face verification only after backend-confirmed check-in", async () => {
    const startFaceVerification = vi.fn();
    const stopFaceVerification = vi.fn();
    installNativeBridge({ startFaceVerification, stopFaceVerification });
    let seatStatus: "vacant" | "checked_in" = "vacant";
    mockFetch.mockImplementation((url: string) =>
      createSeatMock(seatStatus)(url),
    );

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await waitFor(() =>
      expect(startFaceVerification).toHaveBeenCalledTimes(1),
    );

    seatStatus = "checked_in";
    await triggerWsEvent("check_in", 1, { seat_id: 1, attendee_id: 1 });

    await waitFor(() =>
      expect(stopFaceVerification).toHaveBeenCalledTimes(1),
    );
  });

  it("automatically submits only a VALIDATED identity result", async () => {
    installNativeBridge();
    const identityCalls: Array<{
      url: string;
      body: unknown;
      headers?: HeadersInit;
    }> = [];
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/seats/1/identity-checkin") {
        identityCalls.push({
          url,
          body: JSON.parse(String(opts?.body)),
          headers: opts?.headers,
        });
        return okResponse({
          seat_id: 1,
          status: "checked_in",
          attendee_id: 42,
          updated_at: "2026-01-01T00:00:00Z",
        });
      }
      return createSeatMock("occupied_unchecked")(url);
    });
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await screen.findByTestId("native-identity-panel");

    act(() => {
      window.dispatchEvent(
        new CustomEvent("smartdesk-native-event", {
          detail: {
            schemaVersion: 1,
            eventId: "verified-event-0001",
            type: "identity_status",
            timestamp: 1_700_000_000_123,
            data: {
              status: "VERIFIED",
              personId: "person_001",
              similarity: 0.82,
              thresholdStatus: "VALIDATED",
              verificationLevel: "VALIDATED",
              modelVersion: "validated-model-v1",
            },
          },
        }),
      );
    });

    await waitFor(() => expect(identityCalls).toHaveLength(1));
    expect(identityCalls[0].body).toMatchObject({
      eventId: "verified-event-0001",
      eventTimestamp: 1_700_000_000_123,
      personCode: "person_001",
      deviceId: "tablet-seat-01",
      deviceSeatId: 1,
      status: "VERIFIED",
      thresholdStatus: "VALIDATED",
      verificationLevel: "VALIDATED",
    });
    expect(identityCalls[0].headers).toMatchObject({
      "X-SmartDesk-Device-Token":
        "device-secret-token-00000001",
    });
  });

  it("automatically submits a PROTOTYPE result for backend policy evaluation", async () => {
    installNativeBridge();
    const identityCalls: string[] = [];
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/seats/1/identity-checkin") {
        identityCalls.push(url);
      }
      return createSeatMock("occupied_unchecked")(url);
    });
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await screen.findByTestId("native-identity-panel");

    act(() => {
      window.dispatchEvent(
        new CustomEvent("smartdesk-native-event", {
          detail: {
            schemaVersion: 1,
            eventId: "prototype-event-0001",
            type: "identity_status",
            timestamp: 1_700_000_000_456,
            data: {
              status: "VERIFIED",
              personId: "person_001",
              similarity: 0.82,
              thresholdStatus: "PROVISIONAL",
              verificationLevel: "PROTOTYPE",
            },
          },
        }),
      );
    });

    await screen.findByText(/已验证 \/ VERIFIED.*人员编号 person_001.*相似度 0\.820.*原型验证 \/ PROTOTYPE/);
    await waitFor(() => expect(identityCalls).toHaveLength(1));
    expect(screen.queryByText("提交测试签到")).not.toBeInTheDocument();
  });

  it("retries a server failure with the same identity event id", async () => {
    installNativeBridge();
    const eventIds: string[] = [];
    let attempts = 0;
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/seats/1/identity-checkin") {
        attempts += 1;
        eventIds.push(JSON.parse(String(opts?.body)).eventId);
        if (attempts === 1) {
          return {
            ok: false,
            status: 500,
            json: async () => ({
              success: false,
              message: "temporary failure",
              error_code: "TEMPORARY_FAILURE",
            }),
          };
        }
        return okResponse({
          seat_id: 1,
          status: "checked_in",
          attendee_id: 42,
          updated_at: "2026-01-01T00:00:00Z",
        });
      }
      return createSeatMock("occupied_unchecked")(url);
    });
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await screen.findByTestId("native-identity-panel");

    act(() => {
      window.dispatchEvent(
        new CustomEvent("smartdesk-native-event", {
          detail: {
            schemaVersion: 1,
            eventId: "retry-event-0001",
            type: "identity_status",
            timestamp: 1_700_000_000_789,
            data: {
              status: "VERIFIED",
              personId: "person_001",
              similarity: 0.82,
              thresholdStatus: "VALIDATED",
              verificationLevel: "VALIDATED",
              modelVersion: "validated-model-v1",
            },
          },
        }),
      );
    });

    await waitFor(() => expect(eventIds).toHaveLength(2), { timeout: 2_500 });
    expect(eventIds).toEqual(["retry-event-0001", "retry-event-0001"]);
  });

  it("vacates a checked-in seat only after tablet confirmation", async () => {
    installNativeBridge();
    const vacateCalls: Array<{
      body: Record<string, unknown>;
      headers?: HeadersInit;
    }> = [];
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/seats/1/tablet-vacate") {
        vacateCalls.push({
          body: JSON.parse(String(opts?.body)),
          headers: opts?.headers,
        });
        return okResponse({
          seat_id: 1,
          status: "vacant",
          attendee_id: null,
          updated_at: "2026-01-01T00:00:00Z",
        });
      }
      return createSeatMock("checked_in")(url);
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    fireEvent.click(
      await screen.findByText(/确认离席.*Confirm Vacate/),
    );

    await waitFor(() => expect(vacateCalls).toHaveLength(1));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(vacateCalls[0].body).toEqual({
      deviceId: "tablet-seat-01",
      deviceSeatId: 1,
    });
    expect(vacateCalls[0].headers).toMatchObject({
      "X-SmartDesk-Device-Token": "device-secret-token-00000001",
    });
  });

  it("does not vacate when tablet confirmation is cancelled", async () => {
    installNativeBridge();
    const vacateCalls: string[] = [];
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/seats/1/tablet-vacate") {
        vacateCalls.push(url);
      }
      return createSeatMock("checked_in")(url);
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    fireEvent.click(
      await screen.findByText(/确认离席.*Confirm Vacate/),
    );

    expect(vacateCalls).toHaveLength(0);
  });

  it("reports authenticated tablet operational heartbeat", async () => {
    installNativeBridge();
    const heartbeatCalls: Array<{
      body: Record<string, unknown>;
      headers?: HeadersInit;
    }> = [];
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (
        url ===
        "/api/tablet-devices/tablet-seat-01/heartbeat"
      ) {
        heartbeatCalls.push({
          body: JSON.parse(String(opts?.body)),
          headers: opts?.headers,
        });
        return okResponse({
          deviceId: "tablet-seat-01",
          seatId: 1,
          enabled: true,
          lastSeenAt: "2026-01-01T00:00:00Z",
        });
      }
      return createSeatMock("occupied_unchecked")(url);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() =>
      expect(
        heartbeatCalls.some(
          (call) => call.body.meetingWebsocketStatus === "CONNECTED",
        ),
      ).toBe(true),
    );
    const connectedHeartbeat = heartbeatCalls.find(
      (call) => call.body.meetingWebsocketStatus === "CONNECTED",
    );
    expect(connectedHeartbeat?.body).toMatchObject({
      seatId: 1,
      appVersion: "0.8.0",
      cameraStatus: "READY",
      faceModelStatus: "READY",
      registeredTemplatesCount: 2,
      microphoneStatus: "READY",
      meetingWebsocketStatus: "CONNECTED",
      diagnosticStatus: "READY",
      lastError: null,
    });
    expect(connectedHeartbeat?.headers).toMatchObject({
      "X-SmartDesk-Device-Token":
        "device-secret-token-00000001",
    });
  });
});

// ── Voting Tests ────────────────────────────────────────────────────────────

describe("SeatTablet - voting action", () => {
  function mockVoteScenario() {
    mockFetch.mockImplementation((url: string, _opts?: RequestInit) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Board Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({
          id: 10,
          meeting_id: 1,
          title: "Approve Budget",
          options: ["Yes", "No", "Abstain"],
          status: "open",
          is_anonymous: false,
        });
      }
      if (url === "/api/votes/10/statistics") {
        return okResponse({
          vote_id: 10,
          title: "Approve Budget",
          is_anonymous: false,
          status: "open",
          total_votes: 0,
          results: [
            { option: "Yes", count: 0, attendee_ids: [] },
            { option: "No", count: 0, attendee_ids: [] },
            { option: "Abstain", count: 0, attendee_ids: [] },
          ],
        });
      }
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          {
            id: 1,
            meeting_id: 1,
            name: "Alice Wang",
            title: "CEO",
            seat_id: 1,
            checked_in: true,
          },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
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
        return okResponse({
          id: 10,
          meeting_id: 1,
          title: "Approve Budget",
          options: ["Yes", "No", "Abstain"],
          status: "open",
          is_anonymous: false,
        });
      }
      if (typeof originalImpl === "function") {
        return (originalImpl as (url: string, _opts?: RequestInit) => ReturnType<typeof mockFetch>)(
          url,
          opts,
        );
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Active Vote")).toBeInTheDocument();
    });

    // Find and click the "Yes" vote option button
    const yesButtons = screen
      .getAllByText("Yes")
      .filter((el) => el.closest("button"));
    expect(yesButtons.length).toBeGreaterThanOrEqual(1);
    await act(async () => {
      yesButtons[0].closest("button")!.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Wait for submit button to become enabled
    await waitFor(() => {
      const btn = screen.getByText(/提交投票.*Submit Vote/);
      if (btn.hasAttribute("disabled")) throw new Error("Button still disabled");
    });

    const submitBtn = screen.getByText(/提交投票.*Submit Vote/);
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
        return okResponse({
          id: 1,
          title: "Board Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({
          id: 10,
          meeting_id: 1,
          title: "Approve Budget",
          options: ["Yes", "No", "Abstain"],
          status: "open",
          is_anonymous: false,
        });
      }
      if (url === "/api/votes/10/statistics") {
        return okResponse({
          vote_id: 10,
          title: "Approve Budget",
          is_anonymous: false,
          status: "open",
          total_votes: 1,
          results: [
            { option: "Yes", count: 1, attendee_ids: [1] },
            { option: "No", count: 0, attendee_ids: [] },
            { option: "Abstain", count: 0, attendee_ids: [] },
          ],
        });
      }
      if (url === "/api/votes/10/submit") {
        submitCount++;
        const body = opts?.body ? JSON.parse(opts.body as string) : null;
        submitBodies.push(body);
        return okResponse({
          id: 10,
          meeting_id: 1,
          title: "Approve Budget",
          options: ["Yes", "No", "Abstain"],
          status: "open",
          is_anonymous: false,
        });
      }
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          {
            id: 1,
            meeting_id: 1,
            name: "Alice Wang",
            title: "CEO",
            seat_id: 1,
            checked_in: true,
          },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    // Wait for vote section
    await waitFor(() => {
      expect(screen.getByText("Active Vote")).toBeInTheDocument();
    });

    // First submission: select "Yes" and submit
    const firstYes = screen
      .getAllByText("Yes")
      .filter((el) => el.closest("button"));
    await act(async () => {
      firstYes[0].closest("button")!.click();
    });

    // Find submit button
    const allButtons = screen.getAllByRole("button");
    const submitBtn = allButtons.find(
      (b) => b.textContent?.includes("Submit") || b.textContent?.includes("Update"),
    );
    expect(submitBtn).toBeTruthy();

    await act(async () => {
      submitBtn!.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Second submission: select "No" and submit again
    const allNo = screen
      .getAllByText("No")
      .filter((el) => el.closest("button"));
    await act(async () => {
      allNo[0].closest("button")!.click();
    });

    const allButtons2 = screen.getAllByRole("button");
    const submitBtn2 = allButtons2.find(
      (b) => b.textContent?.includes("Submit") || b.textContent?.includes("Update"),
    );
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

// ── Same-Name Attendee Voting Tests ─────────────────────────────────────────

describe("SeatTablet - same-name attendee voting (Task 6)", () => {
  /**
   * Scenario: Two attendees share the same name ("John Doe").
   * Seat 1 is checked in with attendee_id=1 (first John Doe).
   * Seat 2 is checked in with attendee_id=2 (second John Doe).
   * The vote submission must use the seat-bound attendee_id, not name lookup.
   */
  function mockSameNameScenario(seatId: number, boundAttendeeId: number) {
    mockFetch.mockImplementation((url: string, _opts?: RequestInit) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Board Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i + 1 === seatId ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i + 1 === seatId ? boundAttendeeId : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({
          id: 10,
          meeting_id: 1,
          title: "Floor",
          options: ["Option A", "Option B"],
          status: "open",
          is_anonymous: false,
        });
      }
      if (url === "/api/votes/10/statistics") {
        return okResponse({
          vote_id: 10,
          title: "Floor",
          is_anonymous: false,
          status: "open",
          total_votes: 0,
          results: [
            { option: "Option A", count: 0, attendee_ids: [] },
            { option: "Option B", count: 0, attendee_ids: [] },
          ],
        });
      }
      if (url === "/api/meetings/1/attendees") {
        // Both share the same name but have different IDs
        return okResponse([
          { id: 1, meeting_id: 1, name: "John Doe", title: "CEO", seat_id: 1, checked_in: true },
          { id: 2, meeting_id: 1, name: "John Doe", title: "VP", seat_id: 2, checked_in: true },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });
  }

  it("submits vote using attendeeId from seat data, not name lookup", async () => {
    // Seat 1 is bound to attendee_id=1 (first "John Doe")
    mockSameNameScenario(1, 1);

    let submitBody: unknown = null;
    let submitCalled = false;

    // Override for vote submit
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      // Call the scenario mock first to get correct data, then intercept submit
      return (url === "/api/votes/10/submit")
        ? (() => {
            submitCalled = true;
            submitBody = opts?.body ? JSON.parse(opts.body as string) : null;
            return okResponse({
              id: 10,
              meeting_id: 1,
              title: "Floor",
              options: ["Option A", "Option B"],
              status: "open",
              is_anonymous: false,
            });
          })()
        : (mockSameNameScenario(1, 1), null); // We'll handle this differently
    });

    // Re-set the mock properly
    mockFetch.mockReset();
    // Build a proper mock chain
    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/votes/10/submit") {
        submitCalled = true;
        submitBody = opts?.body ? JSON.parse(opts.body as string) : null;
        return okResponse({
          id: 10,
          meeting_id: 1,
          title: "Floor",
          options: ["Option A", "Option B"],
          status: "open",
          is_anonymous: false,
        });
      }
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1,
          status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
          attendee_id: i === 0 ? 1 : null,
          updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") {
        return okResponse({ id: 10, meeting_id: 1, title: "Floor", options: ["Option A", "Option B"], status: "open", is_anonymous: false });
      }
      if (url === "/api/votes/10/statistics") {
        return okResponse({
          vote_id: 10, title: "Floor", is_anonymous: false, status: "open", total_votes: 0,
          results: [
            { option: "Option A", count: 0, attendee_ids: [] },
            { option: "Option B", count: 0, attendee_ids: [] },
          ],
        });
      }
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          { id: 1, meeting_id: 1, name: "John Doe", title: "CEO", seat_id: 1, checked_in: true },
          { id: 2, meeting_id: 1, name: "John Doe", title: "VP", seat_id: null, checked_in: false },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Active Vote")).toBeInTheDocument();
    });

    // Select "Option A"
    const optionABtns = screen.getAllByText("Option A").filter(el => el.closest("button"));
    await act(async () => {
      optionABtns[0].closest("button")!.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Submit vote
    await waitFor(() => {
      const btn = screen.getByText(/提交投票.*Submit Vote/);
      if (btn.hasAttribute("disabled")) throw new Error("Button still disabled");
    });

    const submitBtn = screen.getByText(/提交投票.*Submit Vote/);
    await act(async () => {
      submitBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify vote was submitted with attendee_id=1 (seat-bound), not found by name
    expect(submitCalled).toBe(true);
    expect(submitBody).toEqual({ attendee_id: 1, option: "Option A" });
  });
});

// ── Service Call Tests ──────────────────────────────────────────────────────

describe("SeatTablet - service call actions", () => {
  it("creates a service call when a service button is clicked", async () => {
    let postToServiceCalls = false;

    mockFetch.mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          {
            id: 1,
            meeting_id: 1,
            name: "Alice Wang",
            title: "CEO",
            seat_id: 1,
            checked_in: true,
          },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (
        url.includes("/api/service-calls?meeting_id=1") &&
        opts?.method === "POST"
      ) {
        postToServiceCalls = true;
        return okResponse({
          id: 100,
          meeting_id: 1,
          seat_id: 1,
          service_type: "coffee",
          status: "pending",
          created_at: "2026-01-01T10:05:00Z",
        });
      }
      if (url.includes("/api/service-calls?meeting_id=1"))
        return okResponse([]);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
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
        return okResponse({
          id: 1,
          title: "Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          {
            id: 1,
            meeting_id: 1,
            name: "Alice Wang",
            title: "CEO",
            seat_id: 1,
            checked_in: true,
          },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) {
        return okResponse({
          id: 99,
          meeting_id: 1,
          seat_id: 1,
          service_type: "coffee",
          status: "pending",
          created_at: "2026-01-01T10:05:00Z",
        });
      }
      if (url.includes("/api/service-calls/99/cancel")) {
        cancelCalled = true;
        return okResponse({
          id: 99,
          meeting_id: 1,
          seat_id: 1,
          service_type: "coffee",
          status: "cancelled",
          created_at: "2026-01-01T10:05:00Z",
        });
      }
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Pending/)).toBeInTheDocument();
    });

    // Click Cancel
    const cancelBtn = screen.getByText(/取消 \/ Cancel/);
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
        return okResponse({
          id: 1,
          title: "Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("occupied_unchecked" as const) : ("vacant" as const),
            attendee_id: null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          {
            id: 42,
            meeting_id: 1,
            name: "Charlie",
            title: "VP",
            seat_id: null,
            checked_in: false,
          },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={3} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Seat 3/)).toBeInTheDocument();
    });

    const initialFetches = fetchCount;

    // Simulate checkin_prompt for seat 3 (this seat)
    await act(async () => {
      await triggerWsEvent("checkin_prompt", 1, { seat_id: 3 });
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
      expect(screen.getByTestId("face-access-gate")).toBeInTheDocument();
    });

    // Disconnect WS synchronously
    act(() => {
      wsDisconnect();
    });

    await waitFor(() => {
      expect(screen.getByText(/后端连接已断开/)).toBeInTheDocument();
    });
  });

  it("does not expose write buttons when disconnected at the gate", async () => {
    mockDemoControls = true;
    mockFetch.mockImplementation(createSeatMock("vacant"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("face-access-gate")).toBeInTheDocument();
    });

    // Disconnect WS synchronously
    act(() => {
      wsDisconnect();
    });

    await waitFor(() => {
      expect(screen.getByText(/后端连接已断开/)).toBeInTheDocument();
    });

    expect(screen.queryByText(/模拟入座.*Occupy Seat \(Demo\)/)).not.toBeInTheDocument();
  });
});

// ── Voice Placeholder (removed) ──────────────────────────────────────────────

describe("SeatTablet - old voice placeholder removed", () => {
  it("does not show the old placeholder text", async () => {
    mockFetch.mockImplementation(createSeatMock("vacant"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("face-access-gate")).toBeInTheDocument();
    });

    expect(screen.queryByText(/语音识别接口预留/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Speech recognition interface reserved/),
    ).not.toBeInTheDocument();
  });
});

// ── Speech Control Tests ────────────────────────────────────────────────────

// Helper: wait for the speech WS to be created and send the "started" response.
async function connectSpeechWs(): Promise<void> {
  const speechWs = await waitFor(() => {
    const ws = findSpeechWs();
    if (!ws) throw new Error("Speech WS not created yet");
    return ws;
  });

  // Simulate server sending "started" — this resolves the connect() promise.
  // Wrap in await act(async) so Promise microtask state updates are tracked.
  if (speechWs.onmessage) {
    await act(async () => {
      speechWs.onmessage!({
        data: JSON.stringify({
          type: "started",
          utterance_id: "utt_1_1_000001",
          session_key: "speech_1_1",
        }),
      });
    });
  }
  await new Promise((r) => setTimeout(r, 50));
}

describe("SeatTablet - speech control (non-speaker)", () => {
  /** Seat 1 is not a speaker seat (speaker is null or different seat). */
  function mockNonSpeaker() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Board Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 3 }); // speaker is seat 3
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          {
            id: 1,
            meeting_id: 1,
            name: "Alice Wang",
            title: "CEO",
            seat_id: 1,
            checked_in: true,
          },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      if (url.includes("/api/speech/status"))
        return okResponse({
          ready: true,
          preloading: false,
          streaming_model: "loaded",
          offline_model: "loaded",
          punctuation_model: "loaded",
          punctuation_fallback: false,
          last_error: null,
        });
      return okResponse(null);
    });
  }

  it("shows read-only message when seat is not speaker", async () => {
    mockNonSpeaker();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(
        screen.getByText(/仅当前发言席可识别.*Only the current speaker seat can use speech recognition/),
      ).toBeInTheDocument();
    });

    // No Start button
    expect(screen.queryByText("Start")).not.toBeInTheDocument();
  });

  it("does not show Start button for non-speaker seat", async () => {
    mockNonSpeaker();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(
        screen.getByText(/仅当前发言席可识别.*Only the current speaker seat can use speech recognition/),
      ).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /Start/i })).not.toBeInTheDocument();
  });
});

describe("SeatTablet - speech control (speaker seat)", () => {
  /** Seat 1 IS the speaker seat. */
  function mockSpeakerCheckedIn() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Board Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          {
            id: 1,
            meeting_id: 1,
            name: "Alice Wang",
            title: "CEO",
            seat_id: 1,
            checked_in: true,
          },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      if (url.includes("/api/speech/status"))
        return okResponse({
          ready: true,
          preloading: false,
          streaming_model: "loaded",
          offline_model: "loaded",
          punctuation_model: "loaded",
          punctuation_fallback: false,
          last_error: null,
        });
      return okResponse(null);
    });
  }

  it("shows Start button for speaker seat", async () => {
    mockSpeakerCheckedIn();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });
  });

  it("calls getUserMedia when Start is clicked", async () => {
    mockSpeakerCheckedIn();

    // Import the mock from test-setup to track calls
    const { mockGetUserMedia } = await import("../test-setup");

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // getUserMedia should have been called
    expect(mockGetUserMedia).toHaveBeenCalled();
  });

  it("creates /ws/speech/{meeting_id}?seat=N after clicking Start", async () => {
    mockSpeakerCheckedIn();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 200));
    });

    // Verify speech WS was created with correct URL
    const speechWs = findSpeechWs();
    expect(speechWs).not.toBeNull();
    expect(speechWs!.url).toContain("/ws/speech/1");
    expect(speechWs!.url).toContain("seat=1");
  });

  it("sends start control message on WS open", async () => {
    mockSpeakerCheckedIn();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 200));
    });

    // Check sent messages include the start command
    const msgs = speechWsSentMessages();
    const startMsg = msgs.find((m) => m.includes('"type":"start"'));
    expect(startMsg).toBeTruthy();
    if (startMsg) {
      const parsed = JSON.parse(startMsg);
      expect(parsed).toMatchObject({
        type: "start",
        sample_rate: 16000,
        encoding: "pcm_s16le",
        channels: 1,
      });
    }
  });

  it("transitions to recording after receiving started response", async () => {
    mockSpeakerCheckedIn();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Send the "started" response from the server
    await connectSpeechWs();

    // Should now show recording state
    await waitFor(() => {
      expect(screen.getByText("Streaming audio...")).toBeInTheDocument();
    });
    expect(screen.getByText("Recording")).toBeInTheDocument();
  });

  it("sends PCM16 binary frames to speech WS", async () => {
    mockSpeakerCheckedIn();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await connectSpeechWs();

    await waitFor(() => {
      expect(screen.getByText("Streaming audio...")).toBeInTheDocument();
    });

    // Verify the speech WS is open and ready for binary PCM16 frames
    const speechWs = findSpeechWs();
    expect(speechWs).not.toBeNull();
    expect(speechWs!.readyState).toBe(MultiMockWebSocket.OPEN);

    // The MicrophoneCapture → SpeechWsClient forwarding is tested by the
    // useSpeechStream hook. Here we confirm the WS is in recording state.
  });

  it("sends end_hint and delays WS close (Task 126)", async () => {
    mockSpeakerCheckedIn();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await connectSpeechWs();

    await waitFor(() => {
      expect(screen.getByText("Streaming audio...")).toBeInTheDocument();
    });

    // Save speech WS reference before Stop.
    const speechWs = findSpeechWs();
    expect(speechWs).not.toBeNull();

    // Click Stop
    const stopBtn = screen.getByText("Stop");
    await act(async () => {
      stopBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Check sentData on the saved reference — end_hint was sent
    const sentMessages = speechWs!.sentData.filter(
      (d): d is string => typeof d === "string",
    );
    expect(
      sentMessages.some((m) => m.includes('"type":"end_hint"')),
    ).toBe(true);

    // Task 126: WS should NOT be closed immediately (2000ms delay).
    // Only end_hint was sent; cleanup is deferred.
    const wsAfterStop = findSpeechWs();
    expect(wsAfterStop).not.toBeNull();
  });

  it("sends cancel and stops tracks on Cancel", async () => {
    mockSpeakerCheckedIn();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await connectSpeechWs();

    await waitFor(() => {
      expect(screen.getByText("Streaming audio...")).toBeInTheDocument();
    });

    // Save reference before clicking Cancel
    const speechWs = findSpeechWs();
    expect(speechWs).not.toBeNull();

    // Click Cancel
    const cancelBtn = screen.getByText("Cancel");
    await act(async () => {
      cancelBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Check sentData on the saved reference
    const sentMessages = speechWs!.sentData.filter(
      (d): d is string => typeof d === "string",
    );
    expect(sentMessages.some((m) => m.includes('"type":"cancel"'))).toBe(true);

    // Should return to idle
    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });
  });

  it("updates on utterance_started from speech WS and shows new utterance interim", async () => {
    mockSpeakerCheckedIn();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    // Click Start → speech WS opens → send "started" response
    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    const speechWs = await waitFor(() => {
      const ws = findSpeechWs();
      if (!ws) throw new Error("Speech WS not created");
      return ws;
    });

    // Simulate "started" → recording begins
    if (speechWs.onmessage) {
      await act(async () => {
        speechWs.onmessage!({
          data: JSON.stringify({
            type: "started",
            utterance_id: "utt_1_1_000001",
            session_key: "speech_1_1",
          }),
        });
      });
      await new Promise((r) => setTimeout(r, 50));
    }

    await waitFor(() => {
      expect(screen.getByText("Streaming audio...")).toBeInTheDocument();
    });

    // Simulate "utterance_started" — backend auto-finalised old utterance,
    // started a new one (same speech WS, no reconnect).
    if (speechWs.onmessage) {
      await act(async () => {
        speechWs.onmessage!({
          data: JSON.stringify({
            type: "utterance_started",
            utterance_id: "utt_1_1_000002",
          }),
        });
      });
      await new Promise((r) => setTimeout(r, 50));
    }

    // Send translation_interim for the NEW utterance on meeting WS
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_1_1_000002",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "第二句语音内容。",
              translated_text: "",
              is_final: false,
              caption: {
                previous_line: "",
                current_line: "第二句语音内容。",
                mode: "two_line",
              },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify live caption for the new utterance appears in DOM
    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-utterance-id", "utt_1_1_000002");
      expect(screen.getByTestId("live-caption-current")).toHaveTextContent("第二句语音内容。");
    });
  });

  it("shows error state on backend error message", async () => {
    mockSpeakerCheckedIn();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Send an error response instead of started
    const speechWs = await waitFor(() => {
      const ws = findSpeechWs();
      if (!ws) throw new Error("Speech WS not created yet");
      return ws;
    });

    if (speechWs.onmessage) {
      await act(async () => {
        speechWs.onmessage!({
          data: JSON.stringify({
            type: "error",
            code: "NOT_SPEAKER_SEAT",
            message: "Only the speaker seat may stream audio",
          }),
        });
      });
    }
    await new Promise((r) => setTimeout(r, 50));

    // Should show error state
    await waitFor(() => {
      expect(
        screen.getByText("Only the speaker seat may stream audio"),
      ).toBeInTheDocument();
    });

    // Should show Retry button
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });

  // ── Speech model status dependent tests ────────────────────────────────

  /**
   * Create a mock fetch implementation for a speaker seat with a custom
   * /api/speech/status response. All other endpoints behave like
   * mockSpeakerCheckedIn().
   */
  function mockSpeakerWithSpeechStatus(
    speechStatus: Record<string, unknown>,
  ) {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Board Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{
          id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO",
          seat_id: 1, checked_in: true,
        }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      if (url.includes("/api/speech/status"))
        return okResponse(speechStatus);
      return okResponse(null);
    });
  }

  it("shows Start enabled when speech ready with punctuation fallback", async () => {
    mockSpeakerWithSpeechStatus({
      ready: true,
      preloading: false,
      streaming_model: "loaded",
      offline_model: "loaded",
      punctuation_model: "error",
      punctuation_fallback: true,
      last_error: null,
    });
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    // Must NOT be disabled when ASR is ready despite punctuation fallback
    expect(startBtn).not.toBeDisabled();
  });

  it("shows punctuation fallback hint when fallback is active", async () => {
    mockSpeakerWithSpeechStatus({
      ready: true,
      preloading: false,
      streaming_model: "loaded",
      offline_model: "loaded",
      punctuation_model: "error",
      punctuation_fallback: true,
      last_error: null,
    });
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(
        screen.getByText("Chinese punctuation model unavailable — basic fallback active"),
      ).toBeInTheDocument();
    });
  });

  it("disables Start and shows loading when models are loading", async () => {
    mockSpeakerWithSpeechStatus({
      ready: false,
      preloading: true,
      streaming_model: "loading",
      offline_model: "loading",
      punctuation_model: "unknown",
      // Legacy backends reported fallback=true while the model was only
      // loading. The UI must not turn that transitional state into an error.
      punctuation_fallback: true,
      last_error: null,
    });
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Loading models")).toBeInTheDocument();
    });
    expect(screen.queryByText(/punctuation model unavailable/i)).not.toBeInTheDocument();

    // Start should not be rendered during loading (not idle)
    // The "Waiting for speech models..." text should appear instead
    expect(screen.getByText("Waiting for speech models...")).toBeInTheDocument();
  });

  it("disables Start and shows speech loading message when models are in error state", async () => {
    mockSpeakerWithSpeechStatus({
      ready: false,
      preloading: false,
      streaming_model: "error",
      offline_model: "error",
      punctuation_model: "error",
      punctuation_fallback: true,
      last_error: "streaming model failed to load",
    });
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Speech models loading...")).toBeInTheDocument();
    });

    // Start button IS rendered but DISABLED when models not ready
    const startBtn = screen.getByText("Start").closest("button");
    expect(startBtn).toBeInTheDocument();
    expect(startBtn).toBeDisabled();
  });
});

// ── Data Fetching Tests ─────────────────────────────────────────────────────

describe("SeatTablet - closed vote results", () => {
  it("shows final vote result and disables submission after vote closes", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Board Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/votes?meeting_id=1") {
        return okResponse([
          { id: 21, meeting_id: 1, title: "Approve Roadmap", options: ["Approve", "Reject"], status: "closed", is_anonymous: false },
        ]);
      }
      if (url === "/api/votes/21/statistics") {
        return okResponse({
          vote_id: 21,
          title: "Approve Roadmap",
          is_anonymous: false,
          status: "closed",
          total_votes: 2,
          results: [
            { option: "Approve", count: 1, attendee_ids: [1] },
            { option: "Reject", count: 1, attendee_ids: [2] },
          ],
        });
      }
      if (url === "/api/meetings/1/attendees") {
        return okResponse([
          { id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true },
        ]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      if (url.includes("/api/speech/status")) {
        return okResponse({
          ready: false,
          preloading: false,
          streaming_model: "unknown",
          offline_model: "unknown",
          punctuation_model: "unknown",
          punctuation_fallback: false,
          last_error: null,
        });
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Final Result")).toBeInTheDocument();
    });

    expect(screen.getByText("Approve Roadmap")).toBeInTheDocument();
    expect(screen.getByText("Your choice:")).toBeInTheDocument();
    expect(screen.getAllByText("Approve").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("Submit Vote")).not.toBeInTheDocument();
    expect(screen.queryByText("Update Vote")).not.toBeInTheDocument();
  });
});

describe("SeatTablet - data fetching", () => {
  it("fetches seat-specific current service call for the correct seat", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: "vacant" as const,
            attendee_id: null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) {
        expect(url).toContain("seat_id=3");
        return okResponse(null);
      }
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={3} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Seat 3/)).toBeInTheDocument();
    });
  });
});

// ── Live Caption Display Tests ────────────────────────────────────────────────

describe("SeatTablet - live caption display", () => {
  function mockSpeakerWithCaption() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });
  }

  it("shows two-line live caption on seat UI when interim has caption", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send translation_interim with caption via meeting WS
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_seat_cap_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "今天天气真好，我们出去散步了。",
              translated_text: "",
              is_final: false,
              caption: {
                previous_line: "今天天气真好，",
                current_line: "我们出去散步了。",
                mode: "two_line",
              },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption should appear on the seat UI with correct data-* attributes
    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-utterance-id", "utt_seat_cap_001");
      expect(el).toHaveAttribute("data-seat-id", "1");
      expect(el).toHaveAttribute("data-revision", "1");
      expect(screen.getByTestId("live-caption-previous")).toHaveTextContent("今天天气真好，");
      expect(screen.getByTestId("live-caption-current")).toHaveTextContent("我们出去散步了。");
    });
  });

  it("merges a trailing realtime translation without replacing newer source text", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Alice Wang")).toBeInTheDocument());

    const ws = findMeetingWs();
    await act(async () => {
      ws?.onmessage?.({ data: JSON.stringify({
        event: "translation_interim", meeting_id: 1, timestamp: 1,
        payload: {
          utterance_id: "utt_live_mt", seat_id: 1, revision: 5,
          source_lang: "zh", target_lang: "en", source_text: "这是更新后的实时识别",
          translation_source_text: "这是更新后的实时识别", translated_text: "", is_final: false,
          caption: { previous_line: "", current_line: "这是更新后的实时识别", mode: "two_line" },
        },
      }) });
      ws?.onmessage?.({ data: JSON.stringify({
        event: "translation_interim", meeting_id: 1, timestamp: 2,
        payload: {
          utterance_id: "utt_live_mt", seat_id: 1, revision: 3,
          translation_revision: 3, translation_only: true,
          source_lang: "zh", target_lang: "en", source_text: "这是更新后的实时识别",
          translation_source_text: "这是更新后的实时识别",
          translated_text: "This is the updated live translation.", is_final: false,
        },
      }) });
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(screen.getByTestId("live-caption-current")).toHaveTextContent("这是更新后的实时识别");
    expect(screen.getByTestId("live-caption-translation")).toHaveTextContent("This is the updated live translation.");

    await act(async () => {
      ws?.onmessage?.({ data: JSON.stringify({
        event: "translation_interim", meeting_id: 1, timestamp: 3,
        payload: {
          utterance_id: "utt_live_mt", seat_id: 1, revision: 6,
          source_lang: "zh", target_lang: "en", source_text: "已经滚动到新的两行",
          translation_source_text: "已经滚动到新的两行", translated_text: "", is_final: false,
          caption: { previous_line: "已经滚动到", current_line: "新的两行", mode: "two_line" },
        },
      }) });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.queryByTestId("live-caption-translation")).not.toBeInTheDocument();
    expect(screen.getByTestId("live-caption-translation-pending")).toBeInTheDocument();

    await act(async () => {
      ws?.onmessage?.({ data: JSON.stringify({
        event: "translation_interim", meeting_id: 1, timestamp: 4,
        payload: {
          utterance_id: "utt_live_mt", seat_id: 1, revision: 6,
          translation_revision: 6, translation_only: true,
          source_lang: "zh", target_lang: "en", source_text: "已经滚动到新的两行",
          translation_source_text: "已经滚动到新的两行",
          translated_text: "The newly scrolled two lines.", is_final: false,
        },
      }) });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(screen.getByTestId("live-caption-translation")).toHaveTextContent("The newly scrolled two lines.");
  });

  it("shows transcript-interim when caption is absent (fallback to source_text)", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send translation_interim WITHOUT caption field
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_seat_nocap_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "这是没有字幕的中间结果",
              translated_text: "",
              is_final: false,
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Should NOT render a live-caption block (no caption field)
    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    // Instead, should render transcript-interim with source_text
    await waitFor(() => {
      const interimEl = screen.getByTestId("transcript-interim");
      expect(interimEl).toBeInTheDocument();
      expect(interimEl).toHaveTextContent("这是没有字幕的中间结果");
    });
  });

  it("shows transcript-interim when caption has empty lines (fallback to source_text)", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send translation_interim WITH caption but both lines empty
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_seat_empt_cap_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "字幕为空时的后备文本",
              translated_text: "",
              is_final: false,
              caption: {
                previous_line: "",
                current_line: "",
                mode: "two_line",
              },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Should NOT render a live-caption block (empty caption lines)
    // Our fix routes it to textInterims → InterimRow
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
      const interimEl = screen.getByTestId("transcript-interim");
      expect(interimEl).toHaveTextContent("字幕为空时的后备文本");
    });
  });

  it("removes live caption and shows final record after translation_final", async () => {
    let firstTranslationsCall = true;
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) {
        if (firstTranslationsCall) {
          firstTranslationsCall = false;
          return okResponse({ meeting_id: 1, entries: [] });
        }
        return okResponse({
          meeting_id: 1,
          entries: [
            {
              id: 20,
              meeting_id: 1,
              seat_id: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "今天的会议讨论了几个重要议题。",
              translated_text: "Today's meeting discussed several important topics.",
              created_at: "2026-01-01T10:05:00Z",
              utterance_id: "utt_seat_final_001",
            },
          ],
        });
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send translation_interim with caption
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_seat_final_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "今天的会议讨论了几个重要议题。",
              translated_text: "",
              is_final: false,
              caption: {
                previous_line: "今天的会议讨论了",
                current_line: "几个重要议题。",
                mode: "two_line",
              },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption should appear with correct data-* attributes
    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-utterance-id", "utt_seat_final_001");
      expect(el).toHaveAttribute("data-seat-id", "1");
      expect(el).toHaveAttribute("data-revision", "1");
    });

    // Send translation_final for the same utterance_id
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_final",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              translation_id: 20,
              utterance_id: "utt_seat_final_001",
              seat_id: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "今天的会议讨论了几个重要议题。",
              translated_text: "Today's meeting discussed several important topics.",
              source_type: "offline_rescore",
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 300));
    });

    // Live caption should be removed and final record should appear
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
      expect(screen.getByText("Today's meeting discussed several important topics.")).toBeInTheDocument();
    });
  });
});

// ── Task 7: Translation Visibility & Sorting Tests ───────────────────────

describe("SeatTablet - meeting-wide translations (Task 7)", () => {
  it("fetches translations without seat_id for seat 1", async () => {
    const fetchedUrls: string[] = [];

    mockFetch.mockImplementation((url: string) => {
      fetchedUrls.push(url);
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1, status: "vacant" as const, attendee_id: null, updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/translations")) {
        return okResponse({ meeting_id: 1, entries: [] });
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Seat 1/)).toBeInTheDocument();
    });

    const translationUrl = fetchedUrls.find((u) => u.includes("/api/translations"));
    expect(translationUrl).toBeTruthy();
    expect(translationUrl).toContain("meeting_id=1");
    expect(translationUrl).not.toContain("seat_id");
  });

  it("fetches translations without seat_id for seat 2", async () => {
    const fetchedUrls: string[] = [];

    mockFetch.mockImplementation((url: string) => {
      fetchedUrls.push(url);
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1, status: "vacant" as const, attendee_id: null, updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/translations")) {
        return okResponse({ meeting_id: 1, entries: [] });
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={2} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Seat 2/)).toBeInTheDocument();
    });

    const translationUrl = fetchedUrls.find((u) => u.includes("/api/translations"));
    expect(translationUrl).toBeTruthy();
    expect(translationUrl).toContain("meeting_id=1");
    expect(translationUrl).not.toContain("seat_id");
  });

  it("fetches translations without seat_id for seat 3", async () => {
    const fetchedUrls: string[] = [];

    mockFetch.mockImplementation((url: string) => {
      fetchedUrls.push(url);
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1, status: "vacant" as const, attendee_id: null, updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/translations")) {
        return okResponse({ meeting_id: 1, entries: [] });
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={3} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Seat 3/)).toBeInTheDocument();
    });

    const translationUrl = fetchedUrls.find((u) => u.includes("/api/translations"));
    expect(translationUrl).toBeTruthy();
    expect(translationUrl).toContain("meeting_id=1");
    expect(translationUrl).not.toContain("seat_id");
  });

  it("shows seat 1's final translation on seat 1 after translation_final refresh", async () => {
    let translationsCallCount = 0;

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1, status: i === 0 ? "checked_in" as const : "vacant" as const, attendee_id: i === 0 ? 1 : null, updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([{ id: 1, meeting_id: 1, name: "Alice", title: "", seat_id: 1, checked_in: true }]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/translations")) {
        translationsCallCount++;
        if (translationsCallCount > 1) {
          // Subsequent calls include the final record from seat 1
          return okResponse({
            meeting_id: 1,
            entries: [
              {
                id: 100, meeting_id: 1, seat_id: 1,
                source_lang: "zh", target_lang: "en",
                source_text: "这是测试内容",
                translated_text: "This is test content",
                created_at: "2026-01-01T10:05:00Z",
                utterance_id: "utt_task7_001",
              },
            ],
          });
        }
        return okResponse({ meeting_id: 1, entries: [] });
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Seat 1/)).toBeInTheDocument();
    });

    // Send translation_final to trigger refresh
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_final",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              translation_id: 100,
              utterance_id: "utt_task7_001",
              seat_id: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "这是测试内容",
              translated_text: "This is test content",
              source_type: "offline_rescore",
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 300));
    });

    // Seat 1 should see the final record
    await waitFor(() => {
      expect(screen.getByText("This is test content")).toBeInTheDocument();
    });
  });

  it("shows seat 1's final translation on seat 2 after translation_final refresh", async () => {
    let translationsCallCount = 0;

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1, status: i === 1 ? "checked_in" as const : "vacant" as const, attendee_id: i === 1 ? 2 : null, updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([{ id: 2, meeting_id: 1, name: "Bob", title: "", seat_id: 2, checked_in: true }]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/translations")) {
        translationsCallCount++;
        if (translationsCallCount > 1) {
          return okResponse({
            meeting_id: 1,
            entries: [
              {
                id: 100, meeting_id: 1, seat_id: 1,
                source_lang: "zh", target_lang: "en",
                source_text: "跨座位可见测试",
                translated_text: "Cross-seat visibility test",
                created_at: "2026-01-01T10:05:00Z",
                utterance_id: "utt_cross_seat_001",
              },
            ],
          });
        }
        return okResponse({ meeting_id: 1, entries: [] });
      }
      return okResponse(null);
    });

    render(<SeatTablet seatId={2} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Seat 2/)).toBeInTheDocument();
    });

    // Send translation_final to trigger refresh
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_final",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              translation_id: 100,
              utterance_id: "utt_cross_seat_001",
              seat_id: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "跨座位可见测试",
              translated_text: "Cross-seat visibility test",
              source_type: "offline_rescore",
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 300));
    });

    // Seat 2 should ALSO see seat 1's final record (meeting-wide)
    await waitFor(() => {
      expect(screen.getByText("Cross-seat visibility test")).toBeInTheDocument();
    });
  });
});

// ── Phase 3: Agenda Display Tests ─────────────────────────────────────────────

// ── Task 125: Speech Lifecycle Audit Tests ─────────────────────────────────

describe("SeatTablet - speech lifecycle audit (Task 125)", () => {
  function mockSpeakerWithCaption() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });
  }

  // ── Test 1: Final clears interim ─────────────────────────────────────────
  it("[T125-1] removes interim from interimMap on translation_final", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send interim with caption
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_audit_final_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "审计测试。",
              translated_text: "",
              is_final: false,
              caption: {
                previous_line: "审计",
                current_line: "测试。",
                mode: "two_line",
              },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption should appear
    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-utterance-id", "utt_audit_final_001");
    });

    // Send final — this should remove the interim
    mockFetch.mockImplementation((url: string) => {
      if (url.includes("/api/translations")) {
        return okResponse({ meeting_id: 1, entries: [] });
      }
      // Fall back to speaker mock
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1, status: "vacant" as const, attendee_id: null, updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      return okResponse(null);
    });

    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_final",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              translation_id: 200,
              utterance_id: "utt_audit_final_001",
              seat_id: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "审计测试。",
              translated_text: "Audit test.",
              source_type: "offline_rescore",
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 300));
    });

    // Live caption should be removed
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });
  });

  // ── Test 2: Cancel clears interim ────────────────────────────────────────
  it("[T125-2] removes interim from interimMap on translation_interim_cancelled", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send interim with caption
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_audit_cancel_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "取消测试。",
              translated_text: "",
              is_final: false,
              caption: {
                previous_line: "取消",
                current_line: "测试。",
                mode: "two_line",
              },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption should appear
    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
    });

    // Send cancelled event
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim_cancelled",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_audit_cancel_001",
              seat_id: 1,
              reason: "user_cancelled",
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption should be removed
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });
  });

  // ── Test 3: Late interim after final (fixed by Task 126) ────────────────────
  it("[T125-3] FIXED: late interim after translation_final no longer re-creates live caption", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send interim
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_audit_late_001",
              seat_id: 1,
              revision: 5,
              source_lang: "zh",
              target_lang: "en",
              source_text: "初始中间结果。",
              translated_text: "",
              is_final: false,
              caption: {
                previous_line: "初始",
                current_line: "中间结果。",
                mode: "two_line",
              },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify interim shown
    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
    });

    // Send translation_final (removes interim)
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_final",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              translation_id: 300,
              utterance_id: "utt_audit_late_001",
              seat_id: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "初始中间结果。",
              translated_text: "Initial interim result.",
              source_type: "offline_rescore",
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 200));
    });

    // After final, interim should be gone
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });

    // Now simulate a LATE interim arriving AFTER final (same utterance_id, higher revision)
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_audit_late_001",
              seat_id: 1,
              revision: 6,
              source_lang: "zh",
              target_lang: "en",
              source_text: "延迟到达的中间结果！",
              translated_text: "",
              is_final: false,
              caption: {
                previous_line: "延迟到达的",
                current_line: "中间结果！",
                mode: "two_line",
              },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 200));
    });

    // Task 126 FIX: late interim should NOT re-create live caption because
    // the utterance_id is now tracked as terminal in terminalUtteranceIdsRef.
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });
  });

  // ── Test 4: Stop sends end_hint, WS delayed close (Task 126) ──────────────
  it("[T125-4] Stop sends end_hint and delays WS close (Task 126 fix)", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      if (url.includes("/api/speech/status"))
        return okResponse({
          ready: true, preloading: false, streaming_model: "loaded",
          offline_model: "loaded", punctuation_model: "loaded",
          punctuation_fallback: false, last_error: null,
        });
      return okResponse(null);
    });
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    // Start speech
    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Connect speech WS
    await connectSpeechWs();

    await waitFor(() => {
      expect(screen.getByText("Streaming audio...")).toBeInTheDocument();
    });

    // Save speech WS reference before Stop
    const speechWs = findSpeechWs();
    expect(speechWs).not.toBeNull();

    // Click Stop
    const stopBtn = screen.getByText("Stop");
    await act(async () => {
      stopBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Check that end_hint was sent
    const sentMsgs = speechWs!.sentData.filter(
      (d): d is string => typeof d === "string",
    );
    const hasEndHint = sentMsgs.some((m) => m.includes('"type":"end_hint"'));
    expect(hasEndHint).toBe(true);

    // Task 126 FIX: WS should NOT be closed immediately after Stop.
    // The 2000ms delay window gives the backend time to finalize.
    const wsAfterStop = findSpeechWs();
    expect(wsAfterStop).not.toBeNull();
  });

  // ── Test 5: Cancel sends cancel then immediately closes WS ────────────────
  it("[T125-5] Cancel sends cancel then immediately closes WS (race risk)", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      if (url.includes("/api/speech/status"))
        return okResponse({
          ready: true, preloading: false, streaming_model: "loaded",
          offline_model: "loaded", punctuation_model: "loaded",
          punctuation_fallback: false, last_error: null,
        });
      return okResponse(null);
    });
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    await connectSpeechWs();

    await waitFor(() => {
      expect(screen.getByText("Streaming audio...")).toBeInTheDocument();
    });

    const speechWs = findSpeechWs();
    expect(speechWs).not.toBeNull();

    const cancelBtn = screen.getByText("Cancel");
    await act(async () => {
      cancelBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    const sentMsgs = speechWs!.sentData.filter(
      (d): d is string => typeof d === "string",
    );
    const hasCancel = sentMsgs.some((m) => m.includes('"type":"cancel"'));
    expect(hasCancel).toBe(true);

    // Cancel still closes WS immediately (no delay — intentional)
    const wsAfterCancel = findSpeechWs();
    expect(wsAfterCancel).toBeNull();
  });
});

// ── Task 126: Speech Lifecycle Fix Tests ───────────────────────────────────

describe("SeatTablet - speech lifecycle fixes (Task 126)", () => {
  function mockSpeakerWithCaption() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });
  }

  // ── T126-1: Late interim blocked after translation_final ──────────────────
  it("[T126-1] late translation_interim after final does not show live caption (terminal set)", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send interim for utt_t126_final
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_t126_final_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "第一版。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "", current_line: "第一版。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
    });

    // Send translation_final
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_final",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              translation_id: 400,
              utterance_id: "utt_t126_final_001",
              seat_id: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "第一版。",
              translated_text: "Version one.",
              source_type: "offline_rescore",
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 200));
    });

    // After final, interim should be removed
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });

    // Send LATE interim — should be blocked by terminalUtteranceIdsRef
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_t126_final_001",
              seat_id: 1,
              revision: 2,
              source_lang: "zh",
              target_lang: "en",
              source_text: "延迟到达的第二版！",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "延迟到达的", current_line: "第二版！", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 200));
    });

    // Live caption must NOT re-appear (terminal set blocked it)
    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
  });

  // ── T126-2: Late interim blocked after translation_interim_cancelled ──────
  it("[T126-2] late translation_interim after cancelled does not show live caption", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send interim
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_t126_cancel_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "会被取消的。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "", current_line: "会被取消的。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
    });

    // Send cancelled
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim_cancelled",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_t126_cancel_001",
              seat_id: 1,
              reason: "user_cancelled",
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });

    // Send late interim — should be blocked
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_t126_cancel_001",
              seat_id: 1,
              revision: 2,
              source_lang: "zh",
              target_lang: "en",
              source_text: "延迟到达！",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "延迟", current_line: "到达！", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 200));
    });

    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
  });

  // ── T126-3: New utterance_id still works normally ─────────────────────────
  it("[T126-3] new utterance_id interim still shows live caption (terminal set does not block)", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send interim for new utterance
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_t126_new_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "新的语音内容。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "", current_line: "新的语音内容。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-utterance-id", "utt_t126_new_001");
    });
  });

  // ── T126-4: Duplicate terminal event is idempotent ────────────────────────
  it("accepts a reused utterance_id after meeting WebSocket reconnect", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Alice Wang")).toBeInTheDocument());

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
    await triggerWsEvent("translation_interim", 1, payload);
    await waitFor(() => expect(screen.getByTestId("live-caption")).toBeInTheDocument());
    await triggerWsEvent("translation_final", 1, {
      utterance_id: payload.utterance_id,
      translation_id: 901,
      seat_id: 1,
    });
    await waitFor(() => expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument());

    act(() => wsDisconnect());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 3200));
    });

    await triggerWsEvent("translation_interim", 1, {
      ...payload,
      source_text: "new backend process",
      caption: { previous_line: "", current_line: "new backend process", mode: "two_line" },
    });
    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toHaveAttribute(
        "data-utterance-id", payload.utterance_id,
      );
    });
  }, 10000);

  it("[T126-4] duplicate translation_final for same utterance_id is idempotent", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Alice Wang")).toBeInTheDocument();
    });

    // Send interim
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_t126_dup_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "重复。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "", current_line: "重复。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBeInTheDocument();
    });

    // First final
    mockFetch.mockImplementation((url: string) => {
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      if (url === "/api/meetings/active") return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      if (url === "/api/seats") return okResponse(Array.from({ length: 10 }, (_, i) => ({ seat_id: i + 1, status: "vacant" as const, attendee_id: null, updated_at: "2026-01-01T00:00:00Z" })));
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      return okResponse(null);
    });

    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_final",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: { translation_id: 401, utterance_id: "utt_t126_dup_001", seat_id: 1, source_lang: "zh", target_lang: "en", source_text: "重复。", translated_text: "Dup.", source_type: "offline_rescore" },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 200));
    });

    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });

    // Second final for same utterance_id (duplicate)
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_final",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: { translation_id: 402, utterance_id: "utt_t126_dup_001", seat_id: 1, source_lang: "zh", target_lang: "en", source_text: "重复。", translated_text: "Dup.", source_type: "offline_rescore" },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 200));
    });

    // Should still be gone (no re-render of live caption)
    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
  });
});

// ── Task 129-lite: Speech Stability Tests ────────────────────────────────────

describe("SeatTablet - speech stability (Task 129-lite)", () => {
  function mockSpeaker() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      if (url.includes("/api/speech/status"))
        return okResponse({
          ready: true, preloading: false, streaming_model: "loaded",
          offline_model: "loaded", punctuation_model: "loaded",
          punctuation_fallback: false, last_error: null,
        });
      return okResponse(null);
    });
  }

  // ── Task129-1: Stop → stopping → 2s timeout → idle ─────────────────────
  // Uses real timers (not vi.useFakeTimers) to avoid affecting other tests.
  // The 2500ms wait is necessary for the 2000ms stopTimer in useSpeechStream.
  it("[Task129-1] Stop transitions to stopping, then after 2s returns to idle", async () => {
    mockSpeaker();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    // Wait for Start button
    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    // Click Start → recording
    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
    });
    await connectSpeechWs();

    // Should now be recording
    await waitFor(() => {
      expect(screen.getByText("Streaming audio...")).toBeInTheDocument();
    });

    // Click Stop
    const stopBtn = screen.getByText("Stop");
    await act(async () => {
      stopBtn.click();
    });

    // Should immediately show "Stopping..."
    await waitFor(() => {
      expect(screen.getByText("Stopping...")).toBeInTheDocument();
    });

    // Wait 2500ms for the 2000ms stop timeout to fire
    await act(async () => {
      await new Promise((r) => setTimeout(r, 2500));
    });

    // After timeout, should return to idle with Start button
    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });
  }, 15000);

  // ── Task129-2: Stopping state hides Start button ─────────────────────────
  // Verifies that during the 2s stopping window, "Start" is NOT rendered.
  // Uses real timers — the "Stopping..." check happens immediately after
  // Stop is clicked (before the 2s timeout fires).
  it("[Task129-2] stopping state does not show Start button (prevents re-start)", async () => {
    mockSpeaker();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    const startBtn = screen.getByText("Start");
    await act(async () => {
      startBtn.click();
    });
    await connectSpeechWs();

    await waitFor(() => {
      expect(screen.getByText("Streaming audio...")).toBeInTheDocument();
    });

    // Click Stop — checking behavior DURING the 2s stopping window
    const stopBtn = screen.getByText("Stop");
    await act(async () => {
      stopBtn.click();
    });

    // "Stopping..." visible immediately
    await waitFor(() => {
      expect(screen.getByText("Stopping...")).toBeInTheDocument();
    });

    // Start button should NOT appear during stopping (prevents re-start)
    expect(screen.queryByText("Start")).not.toBeInTheDocument();

    // Wait for stop timeout to fire, then verify Start reappears
    await act(async () => {
      await new Promise((r) => setTimeout(r, 2500));
    });

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });
  }, 15000);

  // ── Task129-3: New utterance still works after Stop → idle cycle ─────────
  it("[Task129-3] new utterance interim still shows after Stop→idle cycle", async () => {
    mockSpeaker();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Start")).toBeInTheDocument();
    });

    // Click Start → recording → Stop → idle (wait for 2s timeout)
    const startBtn = screen.getByText("Start");
    await act(async () => { startBtn.click(); });
    await connectSpeechWs();
    await waitFor(() => expect(screen.getByText("Streaming audio...")).toBeInTheDocument());

    const stopBtn = screen.getByText("Stop");
    await act(async () => { stopBtn.click(); });

    // Wait through the 2s stopping window
    await act(async () => { await new Promise((r) => setTimeout(r, 2500)); });
    await waitFor(() => expect(screen.getByText("Start")).toBeInTheDocument());

    // Now send a new utterance interim via meeting WS — simulating a
    // different speaker seat or new session sending interim independently
    // after the previous speaker's Stop→idle cycle completed.
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_t129_new_001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "停止后的新语音。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "", current_line: "停止后的新语音。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption should appear for the new utterance
    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-utterance-id", "utt_t129_new_001");
    });
  }, 15000);

  it("rolls a finalizing caption to the next utterance without unmounting the live box", async () => {
    mockSpeaker();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Alice Wang")).toBeInTheDocument());
    await waitFor(() => expect(findMeetingWs()?.onmessage).toBeTypeOf("function"));

    const send = (event: string, payload: Record<string, unknown>) => {
      const ws = findMeetingWs();
      ws?.onmessage?.({
        data: JSON.stringify({ event, meeting_id: 1, timestamp: Date.now() / 1000, payload }),
      });
    };
    act(() => send("translation_interim", {
      utterance_id: "utt_roll_old", seat_id: 1, revision: 8,
      source_lang: "zh", target_lang: "en", source_text: "旧段最后一行。",
      translated_text: "The last line of the old segment.", translation_revision: 8, caption: {
        previous_line: "旧段上一行，", current_line: "旧段最后一行。", mode: "two_line",
      },
    }));
    await waitFor(() => expect(screen.getByTestId("live-caption")).toBeInTheDocument());
    const originalNode = screen.getByTestId("live-caption");

    act(() => send("translation_finalizing", {
      utterance_id: "utt_roll_old", next_utterance_id: "utt_roll_next",
      seat_id: 1, source_lang: "zh", target_lang: "en",
      source_text: "旧段最后一行。", boundary_reason: "max_duration",
      rollover_overlap_ms: 300, caption: {
        previous_line: "旧段上一行，", current_line: "旧段最后一行。", mode: "two_line",
      },
    }));

    await waitFor(() => {
      const live = screen.getByTestId("live-caption");
      expect(live).toBe(originalNode);
      expect(live).toHaveAttribute("data-utterance-id", "utt_roll_next");
      expect(screen.queryByTestId("live-caption-placeholder")).not.toBeInTheDocument();
      expect(screen.getByTestId("live-caption-translation")).toHaveTextContent("The last line of the old segment.");
      expect(screen.getByTestId("transcript-pending-final")).toHaveTextContent("旧段最后一行。");
    });

    act(() => send("translation_interim", {
      utterance_id: "utt_roll_next", seat_id: 1, revision: 1,
      source_lang: "zh", target_lang: "en", source_text: "新段内容",
      translated_text: "", caption: {
        previous_line: "", current_line: "新段内容", mode: "two_line",
      },
    }));
    await waitFor(() => {
      expect(screen.getByTestId("live-caption")).toBe(originalNode);
      expect(screen.getByTestId("live-caption-previous")).toHaveTextContent("旧段最后一行。");
      expect(screen.getByTestId("live-caption-current")).toHaveTextContent("新段内容");
    });
  });
});

describe("SeatTablet - current topic display (Phase 3)", () => {
  function mockActiveMeetingWithAgendas(agendas: unknown[]) {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({
          id: 1,
          title: "Board Meeting",
          status: "active",
          started_at: "2026-01-01T10:00:00Z",
        });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse(agendas);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });
  }

  it("shows current active agenda title and ACTIVE status", async () => {
    mockActiveMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening Remarks", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "Budget Review", sort_order: 2, status: "active", started_at: null, completed_at: null, skipped_at: null },
      { id: 3, meeting_id: 1, title: "Q&A", sort_order: 3, status: "pending", started_at: null, completed_at: null, skipped_at: null },
    ]);

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      const titles = screen.getAllByText("Budget Review");
      expect(titles.length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText("进行中")).toBeInTheDocument();
    expect(screen.getByText(/ACTIVE/)).toBeInTheDocument();
  });

  it("shows NO ACTIVE TOPIC when no agenda is active but pending remain", async () => {
    mockActiveMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening Remarks", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "Budget Review", sort_order: 2, status: "pending", started_at: null, completed_at: null, skipped_at: null },
    ]);

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      const els = screen.getAllByText("暂无当前议题");
      expect(els.length).toBeGreaterThanOrEqual(1);
    });
    const noActiveEls = screen.getAllByText(/NO ACTIVE TOPIC/);
    expect(noActiveEls.length).toBeGreaterThanOrEqual(1);
  });

  it("shows ALL TOPICS PROCESSED when all items are completed or skipped", async () => {
    mockActiveMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening Remarks", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "Budget Review", sort_order: 2, status: "skipped", started_at: null, completed_at: null, skipped_at: null },
    ]);

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      const els = screen.getAllByText("所有议题已处理");
      expect(els.length).toBeGreaterThanOrEqual(1);
    });
    const allDoneEls = screen.getAllByText(/ALL TOPICS PROCESSED/);
    expect(allDoneEls.length).toBeGreaterThanOrEqual(1);
  });

  it("does not show any agenda control buttons (Set Current / Advance / Complete / Skip)", async () => {
    mockActiveMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening Remarks", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "Budget Review", sort_order: 2, status: "active", started_at: null, completed_at: null, skipped_at: null },
    ]);

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      const titles = screen.getAllByText("Budget Review");
      expect(titles.length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.queryByText("Set Current")).not.toBeInTheDocument();
    expect(screen.queryByText("Advance")).not.toBeInTheDocument();
    expect(screen.queryByText("Complete")).not.toBeInTheDocument();
    expect(screen.queryByText("Skip")).not.toBeInTheDocument();
  });

  it("shows agenda progress like '2 / 3'", async () => {
    mockActiveMeetingWithAgendas([
      { id: 1, meeting_id: 1, title: "Opening Remarks", sort_order: 1, status: "completed", started_at: null, completed_at: null, skipped_at: null },
      { id: 2, meeting_id: 1, title: "Budget Review", sort_order: 2, status: "active", started_at: null, completed_at: null, skipped_at: null },
      { id: 3, meeting_id: 1, title: "Q&A", sort_order: 3, status: "pending", started_at: null, completed_at: null, skipped_at: null },
    ]);

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Progress/)).toBeInTheDocument();
    });

    expect(screen.getByText(/2 \/ 3/)).toBeInTheDocument();
  });

  it("re-fetches agendas on agenda_updated WS event", async () => {
    let fetchCount = 0;
    mockFetch.mockImplementation((url: string) => {
      fetchCount++;
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1, status: "vacant" as const, attendee_id: null, updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Seat 1/)).toBeInTheDocument();
    });

    const initialFetches = fetchCount;

    // Simulate agenda_updated event via meeting WS
    await act(async () => {
      await triggerWsEvent("agenda_updated", 1, {});
      await new Promise((r) => setTimeout(r, 100));
    });

    // Should have triggered additional fetches
    expect(fetchCount).toBeGreaterThan(initialFetches);
  });

  it("hides the current topic while the seat is gated", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(Array.from({ length: 10 }, (_, i) => ({
          seat_id: i + 1, status: "vacant" as const, attendee_id: null, updated_at: "2026-01-01T00:00:00Z",
        })));
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: null });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") return okResponse([]);
      if (url === "/api/meetings/1/agendas") {
        return okResponse([
          { id: 1, meeting_id: 1, title: "Opening Remarks", sort_order: 1, status: "active", started_at: null, completed_at: null, skipped_at: null },
        ]);
      }
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) return okResponse({ meeting_id: 1, entries: [] });
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("face-access-gate")).toBeInTheDocument();
    });
    expect(screen.queryByText("Opening Remarks")).not.toBeInTheDocument();
  });
});

// ── Task 127A: Speech Local Cleanup Tests ────────────────────────────────────

describe("SeatTablet - speech local cleanup (Task 127A)", () => {
  function mockSpeakerWithCaption() {
    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations"))
        return okResponse({ meeting_id: 1, entries: [] });
      if (url.includes("/api/speech/status"))
        return okResponse({
          ready: true, preloading: false, streaming_model: "loaded",
          offline_model: "loaded", punctuation_model: "loaded",
          punctuation_fallback: false, last_error: null,
        });
      return okResponse(null);
    });
  }

  // ── T127A-1: Cancel immediately removes live caption ────────────────────
  it("[T127A-1] Cancel immediately removes live caption without waiting for WS cancelled event", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Alice Wang")).toBeInTheDocument());

    // Start speech
    const startBtn = screen.getByText("Start");
    await act(async () => { startBtn.click(); await new Promise((r) => setTimeout(r, 50)); });
    await connectSpeechWs();
    await waitFor(() => expect(screen.getByText("Streaming audio...")).toBeInTheDocument());

    // Send interim with caption via meeting WS
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_1_1_000001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "取消测试内容。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "取消测试", current_line: "内容。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Verify live caption appears
    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-utterance-id", "utt_1_1_000001");
    });

    // Click Cancel — triggers local cleanup BEFORE any WS cancelled event
    const cancelBtn = screen.getByText("Cancel");
    await act(async () => {
      cancelBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption must be removed immediately (local cleanup, not via WS)
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });
    // NOTE: We did NOT send translation_interim_cancelled via WS.
    // Cleanup happened purely from the local callback.
  });

  // ── T127A-2: Late interim ignored after Cancel ──────────────────────────
  it("[T127A-2] late translation_interim after Cancel does not re-create live caption", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Alice Wang")).toBeInTheDocument());

    // Start speech
    const startBtn = screen.getByText("Start");
    await act(async () => { startBtn.click(); await new Promise((r) => setTimeout(r, 50)); });
    await connectSpeechWs();
    await waitFor(() => expect(screen.getByText("Streaming audio...")).toBeInTheDocument());

    // Send interim
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_1_1_000001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "会被取消。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "会被", current_line: "取消。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => expect(screen.getByTestId("live-caption")).toBeInTheDocument());

    // Click Cancel
    const cancelBtn = screen.getByText("Cancel");
    await act(async () => {
      cancelBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });
    await waitFor(() => expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument());

    // Send a LATE interim for the same utterance_id (higher revision)
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_1_1_000001",
              seat_id: 1,
              revision: 2,
              source_lang: "zh",
              target_lang: "en",
              source_text: "延迟到达的取消后内容！",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "延迟到达的", current_line: "取消后内容！", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 200));
    });

    // Live caption must NOT reappear (utterance is terminal)
    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
  });

  // ── T127A-3: New utterance after Cancel still shows ────────────────────
  it("[T127A-3] new utterance_id interim still shows live caption after Cancel", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Alice Wang")).toBeInTheDocument());

    // Start speech
    const startBtn = screen.getByText("Start");
    await act(async () => { startBtn.click(); await new Promise((r) => setTimeout(r, 50)); });
    await connectSpeechWs();
    await waitFor(() => expect(screen.getByText("Streaming audio...")).toBeInTheDocument());

    // Send interim for first utterance
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_1_1_000001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "第一句。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "", current_line: "第一句。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => expect(screen.getByTestId("live-caption")).toBeInTheDocument());

    // Click Cancel
    const cancelBtn = screen.getByText("Cancel");
    await act(async () => {
      cancelBtn.click();
      await new Promise((r) => setTimeout(r, 100));
    });
    await waitFor(() => expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument());

    // Send interim for a NEW utterance_id
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_t127a_new_after_cancel_002",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "取消后的新语音。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "取消后的", current_line: "新语音。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    // Live caption should appear for the new utterance
    await waitFor(() => {
      const el = screen.getByTestId("live-caption");
      expect(el).toBeInTheDocument();
      expect(el).toHaveAttribute("data-utterance-id", "utt_t127a_new_after_cancel_002");
    });
  });

  // ── T127A-4: Stop timeout removes live caption ─────────────────────────
  it("[T127A-4] Stop timeout removes live caption after 2 seconds", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Start")).toBeInTheDocument());

    const startBtn = screen.getByText("Start");
    await act(async () => { startBtn.click(); await new Promise((r) => setTimeout(r, 50)); });
    await connectSpeechWs();
    await waitFor(() => expect(screen.getByText("Streaming audio...")).toBeInTheDocument());

    // Send interim
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_1_1_000001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "超时测试。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "超时", current_line: "测试。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => expect(screen.getByTestId("live-caption")).toBeInTheDocument());

    // Click Stop
    const stopBtn = screen.getByText("Stop");
    await act(async () => {
      stopBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // Should show stopping state
    await waitFor(() => expect(screen.getByText("Stopping...")).toBeInTheDocument());

    // Live caption should still be visible DURING the 2s window
    expect(screen.getByTestId("live-caption")).toBeInTheDocument();

    // Wait for the 2s timeout to fire (use real timer, as in Task 129 tests)
    await act(async () => {
      await new Promise((r) => setTimeout(r, 2500));
    });

    // After timeout, live caption should be gone (local cleanup callback fired)
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });
  }, 15000);

  // ── T127A-5: Late interim ignored after Stop timeout ───────────────────
  it("[T127A-5] late translation_interim after Stop timeout does not re-create live caption", async () => {
    mockSpeakerWithCaption();
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Start")).toBeInTheDocument());

    const startBtn = screen.getByText("Start");
    await act(async () => { startBtn.click(); await new Promise((r) => setTimeout(r, 50)); });
    await connectSpeechWs();
    await waitFor(() => expect(screen.getByText("Streaming audio...")).toBeInTheDocument());

    // Send interim
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_1_1_000001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "停止后延迟。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "停止后", current_line: "延迟。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => expect(screen.getByTestId("live-caption")).toBeInTheDocument());

    // Click Stop and wait for timeout
    const stopBtn = screen.getByText("Stop");
    await act(async () => { stopBtn.click(); await new Promise((r) => setTimeout(r, 50)); });
    await act(async () => { await new Promise((r) => setTimeout(r, 2500)); });

    await waitFor(() => expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument());

    // Send late interim for same utterance_id
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_1_1_000001",
              seat_id: 1,
              revision: 2,
              source_lang: "zh",
              target_lang: "en",
              source_text: "延迟到达的停止后内容！",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "延迟到达的", current_line: "停止后内容！", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 200));
    });

    // Live caption must NOT reappear
    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
  }, 15000);

  // ── T127A-6: Final within 2s of Stop still shows history ──────────────
  it("[T127A-6] translation_final within 2s of Stop shows history record, no duplicate cleanup", async () => {
    let translationsCallCount = 0;

    mockFetch.mockImplementation((url: string) => {
      if (url === "/api/meetings/active") {
        return okResponse({ id: 1, title: "Board Meeting", status: "active", started_at: "2026-01-01T10:00:00Z" });
      }
      if (url === "/api/seats") {
        return okResponse(
          Array.from({ length: 10 }, (_, i) => ({
            seat_id: i + 1,
            status: i === 0 ? ("checked_in" as const) : ("vacant" as const),
            attendee_id: i === 0 ? 1 : null,
            updated_at: "2026-01-01T00:00:00Z",
          })),
        );
      }
      if (url === "/api/seats/speaker") return okResponse({ seat_id: 1 });
      if (url === "/api/votes/active") return okResponse(null);
      if (url === "/api/meetings/1/attendees") {
        return okResponse([{ id: 1, meeting_id: 1, name: "Alice Wang", title: "CEO", seat_id: 1, checked_in: true }]);
      }
      if (url === "/api/meetings/1/agendas") return okResponse([]);
      if (url.includes("/api/service-calls/current")) return okResponse(null);
      if (url.includes("/api/translations")) {
        translationsCallCount++;
        if (translationsCallCount > 1) {
          return okResponse({
            meeting_id: 1,
            entries: [{
              id: 500, meeting_id: 1, seat_id: 1,
              source_lang: "zh", target_lang: "en",
              source_text: "停止后最终内容。",
              translated_text: "Final content after stop.",
              created_at: "2026-01-01T10:05:00Z",
              utterance_id: "utt_1_1_000001",
            }],
          });
        }
        return okResponse({ meeting_id: 1, entries: [] });
      }
      if (url.includes("/api/speech/status"))
        return okResponse({
          ready: true, preloading: false, streaming_model: "loaded",
          offline_model: "loaded", punctuation_model: "loaded",
          punctuation_fallback: false, last_error: null,
        });
      return okResponse(null);
    });

    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Start")).toBeInTheDocument());

    const startBtn = screen.getByText("Start");
    await act(async () => { startBtn.click(); await new Promise((r) => setTimeout(r, 50)); });
    await connectSpeechWs();
    await waitFor(() => expect(screen.getByText("Streaming audio...")).toBeInTheDocument());

    // Send interim
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_interim",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              utterance_id: "utt_1_1_000001",
              seat_id: 1,
              revision: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "停止后最终内容。",
              translated_text: "",
              is_final: false,
              caption: { previous_line: "停止后", current_line: "最终内容。", mode: "two_line" },
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 100));
    });

    await waitFor(() => expect(screen.getByTestId("live-caption")).toBeInTheDocument());

    // Click Stop
    const stopBtn = screen.getByText("Stop");
    await act(async () => {
      stopBtn.click();
      await new Promise((r) => setTimeout(r, 50));
    });

    // BEFORE the 2s timeout, send translation_final
    await act(async () => {
      const ws = findMeetingWs();
      if (ws?.onmessage) {
        ws.onmessage({
          data: JSON.stringify({
            event: "translation_final",
            meeting_id: 1,
            timestamp: Math.floor(Date.now() / 1000),
            payload: {
              translation_id: 500,
              utterance_id: "utt_1_1_000001",
              seat_id: 1,
              source_lang: "zh",
              target_lang: "en",
              source_text: "停止后最终内容。",
              translated_text: "Final content after stop.",
              source_type: "offline_rescore",
            },
          }),
        });
      }
      await new Promise((r) => setTimeout(r, 300));
    });

    // Live caption should be removed by the translation_final handler
    await waitFor(() => {
      expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    });

    // History record should appear
    await waitFor(() => {
      expect(screen.getByText("Final content after stop.")).toBeInTheDocument();
    });

    // Now wait for the stop timeout to fire (the local cleanup is a no-op
    // because utterance is already terminal and interim already removed)
    await act(async () => {
      await new Promise((r) => setTimeout(r, 2500));
    });

    // Live caption should still be gone, history should still show
    expect(screen.queryByTestId("live-caption")).not.toBeInTheDocument();
    expect(screen.getByText("Final content after stop.")).toBeInTheDocument();
  }, 15000);
});

describe("SeatTablet - sentence lyric events", () => {
  it("shows the sentence-bound translation received on the meeting socket", async () => {
    mockFetch.mockImplementation(createSeatMock("checked_in"));
    render(<SeatTablet seatId={1} onSwitchToAdmin={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Board Meeting")).toBeInTheDocument());

    const base = {
      utterance_id: "utt_1_1_000001", sentence_id: "utt_1_1_000001:s000001",
      sentence_sequence: 1, seat_id: 1, revision: 3,
      source_lang: "en", target_lang: "zh", source_text: "Welcome everyone.",
    };
    await triggerWsEvent("translation_interim", 1, {
      ...base, sentence_source_text: "Welcome everyone.", sentence_state: "completed",
      translated_text: "", is_final: false,
    });
    await triggerWsEvent("translation_sentence", 1, {
      ...base, translated_text: "欢迎大家。", translation_status: "ok",
    });

    await waitFor(() => {
      expect(screen.getByTestId("live-lyric-source")).toHaveTextContent("Welcome everyone.");
      expect(screen.getByTestId("live-lyric-translation")).toHaveTextContent("欢迎大家。");
    });
  });
});
