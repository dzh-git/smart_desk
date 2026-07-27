import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiGet } from "../../api/client";
import { HardwareStatus } from "../HardwareStatus";

vi.mock("../../api/client", () => ({
  apiGet: vi.fn(),
}));

const mockedApiGet = vi.mocked(apiGet);

function statusFixture(tabletOnline = true) {
  return {
    deploy_mode: "esp32",
    integrated: true,
    tablet_offline_timeout_seconds: 45,
    tablets: [
      {
        seat_id: 1,
        provisioned: true,
        device_id: "tablet-seat-01",
        enabled: true,
        online: tabletOnline,
        last_heartbeat_at: "2026-07-28T02:00:00Z",
        heartbeat_age_seconds: tabletOnline ? 2 : 600,
        app_version: "0.8.0",
        camera_status: "READY",
        face_model_status: "READY",
        registered_templates_count: 3,
        microphone_status: "READY",
        meeting_websocket_status: "CONNECTED",
        diagnostic_status: "READY",
        last_error: null,
      },
    ],
    seats: [
      {
        seat_id: 1,
        enabled: true,
        connected: true,
        port: null,
        current_mode: "MEETING_ACTIVE",
        intended_mode: "MEETING_ACTIVE",
        command_pending: false,
        last_ack_at: 1_785_200_000,
        last_error: null,
        device_type: "esp32",
        device_id: "esp32-seat-01",
        firmware_version: "0.1.0",
        last_heartbeat_at: 1_785_200_000,
        sensor_ok: true,
      },
    ],
    gesture: {
      enabled: true,
      status_ws_url: "ws://127.0.0.1:8765",
      online: true,
    },
  };
}

describe("HardwareStatus device operations view", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders tablet and ESP32 as separate channels per seat", async () => {
    mockedApiGet.mockResolvedValue(statusFixture());
    render(<HardwareStatus />);

    const seat = await screen.findByRole("region", {
      name: "席位 1 设备状态",
    });
    expect(within(seat).getByText("Android 平板")).toBeInTheDocument();
    expect(within(seat).getByText("tablet-seat-01")).toBeInTheDocument();
    expect(
      within(seat).getByText("ESP32 席位控制器"),
    ).toBeInTheDocument();
    expect(within(seat).getByText("esp32-seat-01")).toBeInTheDocument();
    expect(within(seat).getByText(/模板：3/)).toBeInTheDocument();
    expect(within(seat).getByText(/App：0.8.0/)).toBeInTheDocument();
    expect(within(seat).getByText(/在线 · 会议中/)).toBeInTheDocument();
  });

  it("shows a stale tablet offline without changing ESP32 state", async () => {
    mockedApiGet.mockResolvedValue(statusFixture(false));
    render(<HardwareStatus />);

    const seat = await screen.findByRole("region", {
      name: "席位 1 设备状态",
    });
    expect(within(seat).getByText("离线")).toBeInTheDocument();
    expect(within(seat).getByText(/在线 · 会议中/)).toBeInTheDocument();
  });
});
