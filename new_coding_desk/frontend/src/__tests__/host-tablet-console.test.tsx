import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HostTabletConsole } from "../components/HostTabletConsole";

const mocks = vi.hoisted(() => ({
  useSeatData: vi.fn(),
  debugAdmitSeat: vi.fn(),
  identityCheckinSeat: vi.fn(),
}));

vi.mock("../components/AdminDashboard", () => ({
  AdminDashboard: ({ hostSeatCheckIn }: { hostSeatCheckIn?: ReactNode }) => (
    <div data-testid="admin-dashboard">
      HOST ADMIN
      {hostSeatCheckIn}
    </div>
  ),
}));
vi.mock("../hooks/useSeatData", () => ({ useSeatData: mocks.useSeatData }));
vi.mock("../api/resources", () => ({
  debugAdmitSeat: mocks.debugAdmitSeat,
  identityCheckinSeat: mocks.identityCheckinSeat,
}));

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
  };
}

describe("HostTabletConsole", () => {
  beforeEach(() => {
    mocks.useSeatData.mockReturnValue(seatData());
    mocks.debugAdmitSeat.mockResolvedValue({});
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
    installNative({ unlocked: false });
    render(<HostTabletConsole />);

    expect(await screen.findByRole("button", { name: "输入维护 PIN" })).toBeInTheDocument();
    expect(screen.queryByTestId("admin-dashboard")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "输入维护 PIN" }));
    expect(await screen.findByTestId("admin-dashboard")).toBeInTheDocument();
  });

  it("starts formal face verification only after explicit Seat 1 check-in", async () => {
    const native = installNative();
    render(<HostTabletConsole />);

    const button = await screen.findByRole("button", { name: "开始 Seat 1 人脸签到" });
    expect(native.startFaceVerification).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() => expect(native.startFaceVerification).toHaveBeenCalledWith("host-person"));
    expect(screen.getByText("主持人人脸验证")).toBeInTheDocument();
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
});
