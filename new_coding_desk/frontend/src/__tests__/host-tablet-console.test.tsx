import type { ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HostTabletConsole } from "../components/HostTabletConsole";

const mocks = vi.hoisted(() => ({
  useSeatData: vi.fn(),
  debugAdmitSeat: vi.fn(),
  fetchSpeechStatus: vi.fn(),
  identityCheckinSeat: vi.fn(),
}));

vi.mock("../components/AdminDashboard", () => ({
  AdminDashboard: ({
    hostSeatCheckIn,
    hostSpeechControl,
  }: {
    hostSeatCheckIn?: ReactNode;
    hostSpeechControl?: ReactNode;
  }) => (
    <div data-testid="admin-dashboard">
      HOST ADMIN
      <section data-testid="mock-overview">{hostSeatCheckIn}</section>
      <section data-testid="mock-toolbar">{hostSpeechControl}</section>
    </div>
  ),
}));
vi.mock("../hooks/useSeatData", () => ({ useSeatData: mocks.useSeatData }));
vi.mock("../api/resources", () => ({
  debugAdmitSeat: mocks.debugAdmitSeat,
  fetchSpeechStatus: mocks.fetchSpeechStatus,
  identityCheckinSeat: mocks.identityCheckinSeat,
}));
vi.mock("../audio/microphone", async () => {
  const actual = await vi.importActual<typeof import("../audio/microphone")>("../audio/microphone");
  return { ...actual, isMicrophoneCaptureSupported: () => true };
});

function envelope(type: string, data: unknown) {
  return JSON.stringify({
    schemaVersion: 1,
    eventId: `event-${type}`,
    timestamp: 1_700_000_000_000,
    type,
    data,
  });
}

function installNative({
  seatId = 1,
  unlocked = true,
  identityMode = "formal",
}: {
  seatId?: number;
  unlocked?: boolean;
  identityMode?: "formal" | "debug";
} = {}) {
  const startFaceVerification = vi.fn(() => envelope("identity_status", {
    status: "VERIFYING",
    message: "正在验证",
  }));
  window.SmartDeskNative = {
    getDeviceInfo: vi.fn(() => envelope("device_info", {
      deviceId: `tablet-seat-${seatId}`,
      seatId,
      configured: true,
      serverUrl: "http://host:8000",
      frontendUrl: "http://host:5173",
      identityMode,
    })),
    getDeviceCredential: vi.fn(() => envelope("device_credential", {
      deviceToken: "device-token-000000000001",
    })),
    getIdentityStatus: vi.fn(() => envelope("identity_status", { status: "IDLE" })),
    getRegisteredFaces: vi.fn(() => envelope("registered_people", {
      personIds: ["host-person"],
      count: 1,
    })),
    getHostConsoleAccess: vi.fn(() => envelope("host_console_access", {
      granted: unlocked,
      pending: false,
    })),
    requestHostConsoleAccess: vi.fn(() => envelope("host_console_access", {
      granted: true,
      pending: false,
    })),
    getDefaultHostIdentity: vi.fn(() => envelope("host_identity", {
      defaultPersonId: "host-person",
      registeredPersonIds: ["host-person"],
    })),
    setDefaultHostIdentity: vi.fn(),
    startFaceVerification,
    stopFaceVerification: vi.fn(() => envelope("identity_status", { status: "IDLE" })),
    beginMaintenanceHold: vi.fn(),
    cancelMaintenanceHold: vi.fn(),
  };
  return { startFaceVerification };
}

function seatData() {
  return {
    loading: false,
    error: null,
    meeting: { id: 1, title: "会议", status: "active" },
    attendees: [{
      id: 1,
      meeting_id: 1,
      person_id: "host-person",
      name: "主持人",
      title: "",
      assigned_seat_id: 1,
      seat_id: null,
      checked_in: false,
    }],
    seats: [{ seatId: 1, isCheckedIn: false }],
    refresh: vi.fn(),
    speakerSeatId: null,
    connection: "connected",
    terminateUtterance: vi.fn(),
  };
}

describe("HostTabletConsole", () => {
  function checkedInSeatData(speakerSeatId: number | null) {
    const data = seatData();
    return {
      ...data,
      speakerSeatId,
      attendees: data.attendees.map((attendee) => ({
        ...attendee,
        seat_id: 1,
        checked_in: true,
      })),
      seats: [{ seatId: 1, isCheckedIn: true }],
    };
  }

  beforeEach(() => {
    mocks.useSeatData.mockReturnValue(seatData());
    mocks.debugAdmitSeat.mockResolvedValue({});

    mocks.fetchSpeechStatus.mockResolvedValue({
      ready: true,
      preloading: false,
      streaming_model: "loaded",
      offline_model: "loaded",
      punctuation_model: "loaded",
      punctuation_fallback: false,
      translation_model: "loaded",
      translation_models: {},
      last_error: null,
    });
  });
  afterEach(() => {
    delete window.SmartDeskNative;
    vi.clearAllMocks();
  });

  it("rejects an ordinary browser and a non-Seat 1 device", async () => {
    render(<HostTabletConsole />);
    expect(await screen.findByText(/仅允许从已绑定的 Seat 1 Android 平板/)).toBeInTheDocument();

    installNative({ seatId: 2 });
    const second = render(<HostTabletConsole />);
    expect(await screen.findByText(/不是已启用并绑定 Seat 1/)).toBeInTheDocument();
    second.unmount();
  });

  it("does not render the admin dashboard before native PIN unlock", async () => {
    const native = installNative({ unlocked: false });
    render(<HostTabletConsole />);

    expect(await screen.findByRole("button", { name: "输入维护 PIN" })).toBeInTheDocument();
    expect(screen.queryByTestId("admin-dashboard")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "输入维护 PIN" }));
    expect(await screen.findByTestId("admin-dashboard")).toBeInTheDocument();
    expect(native.startFaceVerification).not.toHaveBeenCalled();
  });

  it("starts formal face verification only after explicit Seat 1 check-in", async () => {
    const native = installNative();
    render(<HostTabletConsole />);

    const button = await screen.findByRole("button", { name: "开始 Seat 1 人脸签到" });
    expect(native.startFaceVerification).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() => expect(native.startFaceVerification).toHaveBeenCalledWith("host-person"));
    expect(screen.getByText("主持人人脸验证")).toBeInTheDocument();
    expect(screen.getByTestId("face-live-similarity")).toHaveTextContent("--");
  });

  it("renders the Seat 1 check-in card in normal document flow", async () => {
    installNative();
    render(<HostTabletConsole />);

    const card = await screen.findByTestId("host-seat-checkin-card");
    expect(card.className).not.toContain("fixed");
    expect(card.closest("[data-testid='admin-dashboard']")).toBeInTheDocument();
  });

  it("uses the authenticated debug admission endpoint without camera", async () => {
    const native = installNative({ identityMode: "debug" });
    render(<HostTabletConsole />);

    fireEvent.click(await screen.findByRole("button", { name: "Seat 1 Debug 签到" }));
    await waitFor(() => expect(mocks.debugAdmitSeat).toHaveBeenCalled());
    expect(native.startFaceVerification).not.toHaveBeenCalled();
  });

  it("shows a read-only speech hint when checked-in Seat 1 is not the speaker", async () => {
    installNative();
    mocks.useSeatData.mockReturnValue(checkedInSeatData(2));
    render(<HostTabletConsole />);

    expect(await screen.findByText(/仅当前发言席可识别/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /开始识别/ })).not.toBeInTheDocument();
  });

  it("enables speech recognition when checked-in Seat 1 is the speaker", async () => {
    installNative();
    mocks.useSeatData.mockReturnValue(checkedInSeatData(1));
    render(<HostTabletConsole />);

    fireEvent.click(await screen.findByLabelText("主持席麦克风 / Host Microphone"));
    expect(await screen.findByRole("button", { name: /开始识别/ })).toBeEnabled();
  });

  it("keeps host speech recognition in the toolbar across workspaces", async () => {
    installNative();
    mocks.useSeatData.mockReturnValue(checkedInSeatData(1));
    render(<HostTabletConsole />);

    const overview = await screen.findByTestId("mock-overview");
    const toolbar = screen.getByTestId("mock-toolbar");
    expect(within(toolbar).getByRole("button", { name: /开始识别/, hidden: true })).not.toBeVisible();
    fireEvent.click(within(toolbar).getByLabelText("主持席麦克风 / Host Microphone"));
    expect(
      within(overview).queryByRole("button", { name: /开始识别/ }),
    ).not.toBeInTheDocument();
    expect(
      within(toolbar).getByRole("button", { name: /开始识别/ }),
    ).toBeVisible();
  });

  it("keeps speech read-only until speaker Seat 1 has checked in", async () => {
    installNative();
    mocks.useSeatData.mockReturnValue({ ...seatData(), speakerSeatId: 1 });
    render(<HostTabletConsole />);

    expect(await screen.findByText(/仅当前发言席可识别/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /开始识别/ })).not.toBeInTheDocument();
  });
  it("keeps face diagnostics hidden until verification details are opened", async () => {
    installNative();
    render(<HostTabletConsole />);

    fireEvent.click(await screen.findByRole("button", { name: "开始 Seat 1 人脸签到" }));
    act(() => {
    window.dispatchEvent(new CustomEvent("smartdesk-native-event", {
      detail: {
        schemaVersion: 1,
        eventId: "identity-progress-1",
        timestamp: 1_700_000_000_100,
        type: "identity_status",
        data: {
          status: "VERIFYING",
          message: "自然光已采集3/5",
          similarity: 0.6472,
          threshold: 0.55,
          stageSampleCount: 3,
          stageRequiredSamples: 5,
          matchStreak: 2,
        },
      },
    }));
    });

    expect(await screen.findByTestId("face-live-similarity")).not.toBeVisible();
    expect(screen.getByRole("button", { name: "取消验证" })).toBeVisible();
    fireEvent.click(screen.getByText("验证详情"));
    expect(screen.getByTestId("face-live-similarity")).toBeVisible();
    expect(screen.getByTestId("face-live-similarity")).toHaveTextContent("0.647");
    expect(screen.getByTestId("face-threshold")).toHaveTextContent("0.550");
    expect(screen.getByTestId("face-sample-progress")).toHaveTextContent("3/5");
    expect(screen.getByTestId("face-qualified-frames")).toHaveTextContent("2/4");

    act(() => {
      window.dispatchEvent(new CustomEvent("smartdesk-native-event", {
        detail: {
          schemaVersion: 1,
          eventId: "identity-final-1",
          timestamp: 1_700_000_000_200,
          type: "identity_status",
          data: {
            status: "RETRY_REQUIRED",
            message: "聚合分数达标，但单帧一致性不足",
            similarity: 0.65,
            threshold: 0.55,
            stageSampleCount: 5,
            stageRequiredSamples: 5,
            matchStreak: 3,
          },
        },
      }));
    });
    expect(screen.getByText("最终聚合相似度")).toBeInTheDocument();
    expect(screen.getByTestId("face-live-similarity")).toHaveTextContent("0.650");
  });
});
