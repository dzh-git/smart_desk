import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FaceTemplateManager } from "../components/FaceTemplateManager";

const api = vi.hoisted(() => ({
  createPerson: vi.fn(),
  fetchMeetings: vi.fn(),
  fetchPeople: vi.fn(),
  deleteFaceTemplate: vi.fn(),
  fetchFaceAssignments: vi.fn(),
  fetchFaceTemplateLibrary: vi.fn(),
  fetchTabletFaceSyncStatus: vi.fn(),
  updateFaceAssignments: vi.fn(),
}));

vi.mock("../api/resources", () => ({
  createPerson: api.createPerson,
  fetchMeetings: api.fetchMeetings,
  fetchPeople: api.fetchPeople,
}));

vi.mock("../api/faceTemplates", () => ({
  deleteFaceTemplate: api.deleteFaceTemplate,
  fetchFaceAssignments: api.fetchFaceAssignments,
  fetchFaceTemplateLibrary: api.fetchFaceTemplateLibrary,
  fetchTabletFaceSyncStatus: api.fetchTabletFaceSyncStatus,
  updateFaceAssignments: api.updateFaceAssignments,
}));

function envelope(type: string, data: unknown): string {
  return JSON.stringify({
    schemaVersion: 1,
    eventId: `test-${type}`,
    timestamp: 1_700_000_000_000,
    type,
    data,
  });
}

function installHostEnvironment(localPersonIds: string[]) {
  const removeFaceTemplate = vi.fn(() => envelope("identity_status", {
    status: "IDLE",
    message: "已删除",
  }));
  const applyProvisionalThreshold = vi.fn((value: number) => envelope("identity_status", {
    status: "IDLE",
    threshold: value,
    thresholdStatus: "PROVISIONAL",
    verificationLevel: "PROTOTYPE",
    message: "已应用原型阈值",
  }));
  window.SmartDeskNative = {
    getDeviceInfo: vi.fn(() => envelope("device_info", {
      deviceId: "tablet-seat-01",
      seatId: 1,
      serverUrl: "http://host:8000",
      frontendUrl: "http://host:5173",
      configured: true,
    })),
    getDeviceCredential: vi.fn(() => envelope("device_credential", {
      deviceToken: "device-secret-token-00000001",
    })),
    getIdentityStatus: vi.fn(() => envelope("identity_status", {
      status: "IDLE",
      threshold: null,
      thresholdStatus: "CALIBRATION_PENDING",
      verificationLevel: "NONE",
    })),
    getRegisteredFaces: vi.fn(() => envelope("registered_people", {
      personIds: localPersonIds,
      count: localPersonIds.length,
    })),
    startFaceVerification: vi.fn(),
    stopFaceVerification: vi.fn(),
    removeFaceTemplate,
    applyProvisionalThreshold,
  };
  api.fetchFaceTemplateLibrary.mockResolvedValue({
    count: 1,
    capacity: 81,
    templates: [{
      personId: "participant_02",
      personName: "参会者二",
      modelVersion: "test-model",
      modelHash: "test-hash",
      pipelineVersion: 1,
      revision: 1,
      createdAt: "2026-08-22T00:00:00Z",
      updatedAt: "2026-08-22T00:00:00Z",
    }],
  });
  api.fetchPeople.mockResolvedValue([
    { id: "person_self", name: "主持人", active: true, created_at: "2026-08-22T00:00:00Z" },
    { id: "participant_02", name: "参会者二", active: true, created_at: "2026-08-22T00:00:00Z" },
  ]);
  api.fetchMeetings.mockResolvedValue([]);
  api.fetchTabletFaceSyncStatus.mockResolvedValue([]);
  return { removeFaceTemplate, applyProvisionalThreshold };
}

describe("FaceTemplateManager access gate", () => {
  afterEach(() => {
    delete window.SmartDeskNative;
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("rejects an ordinary browser before loading biometric management data", async () => {
    delete window.SmartDeskNative;
    render(<FaceTemplateManager />);

    expect(await screen.findByText("禁止访问")).toBeInTheDocument();
    expect(screen.getByText(/Seat 1 平板长按右上角图标/)).toBeInTheDocument();
  });

  it("separates host-local templates from central participant templates", async () => {
    const { removeFaceTemplate, applyProvisionalThreshold } = installHostEnvironment(["person_self"]);

    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<FaceTemplateManager />);

    expect(await screen.findByText("主持人本机模板")).toBeInTheDocument();
    expect(screen.getByText("中央参会者模板库")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存为主持人本机模板（Seat 1）" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存到中央参会者模板库（Seat 2–9）" })).toBeInTheDocument();

    const threshold = screen.getByLabelText("原型识别阈值") as HTMLInputElement;
    expect(threshold.value).toBe("0.550");
    fireEvent.click(screen.getByRole("button", { name: "确认当前模型阈值" }));
    await waitFor(() => expect(applyProvisionalThreshold).toHaveBeenCalledWith(0.55));
    expect(await screen.findByText(/原型阈值已确认为 0.550/)).toBeInTheDocument();

    const picker = screen.getByLabelText(/选择 5–20 张 JPG\/PNG 正脸照片/) as HTMLInputElement;
    expect(picker.multiple).toBe(true);
    expect(picker.accept).toContain("image/jpeg");

    fireEvent.click(screen.getByRole("button", { name: "删除主持人本机模板主持人" }));
    await waitFor(() => expect(removeFaceTemplate).toHaveBeenCalledWith("person_self"));
  });

  it.each([0, 1, 2])(
    "allows threshold confirmation with %i host-local templates",
    async (localCount) => {
      const localPersonIds = ["person_self", "participant_02"].slice(0, localCount);
      const { applyProvisionalThreshold } = installHostEnvironment(localPersonIds);
      render(<FaceTemplateManager />);

      const button = await screen.findByRole("button", { name: "确认当前模型阈值" });
      expect(button).toBeEnabled();
      fireEvent.click(button);

      await waitFor(() => expect(applyProvisionalThreshold).toHaveBeenCalledWith(0.55));
    },
  );

  it("assigns a host-local template to Seat 1 independently of central templates", async () => {
    installHostEnvironment(["person_self"]);
    api.fetchMeetings.mockResolvedValue([{
      id: 45,
      title: "主持人分配测试",
      description: "",
      status: "pending",
      created_at: "2026-08-23T00:00:00Z",
      started_at: null,
      ended_at: null,
    }]);
    const assignments = Array.from({ length: 9 }, (_, index) => ({
      seatId: index + 1,
      personId: null,
      attendeeId: null,
      personName: null,
      templateRevision: null,
    }));
    api.fetchFaceAssignments.mockResolvedValue({
      meetingId: 45,
      templateSetRevision: 0,
      assignments,
    });
    api.updateFaceAssignments.mockResolvedValue({
      meetingId: 45,
      templateSetRevision: 1,
      assignments: assignments.map((item) => item.seatId === 1
        ? { ...item, personId: "person_self", personName: "主持人" }
        : item),
    });

    render(<FaceTemplateManager />);

    const hostSelector = await screen.findByLabelText("Seat 1 本场主持人");
    expect(within(hostSelector).getByRole("option", { name: "主持人" })).toBeInTheDocument();
    expect(within(hostSelector).queryByRole("option", { name: "参会者二" })).not.toBeInTheDocument();
    fireEvent.change(hostSelector, { target: { value: "person_self" } });
    fireEvent.click(screen.getByRole("button", { name: "保存席位分配" }));

    await waitFor(() => expect(api.updateFaceAssignments).toHaveBeenCalled());
    expect(api.updateFaceAssignments.mock.calls[0][3]).toContainEqual({
      seatId: 1,
      personId: "person_self",
    });
  });
});
