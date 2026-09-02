import { afterEach, describe, expect, it, vi } from "vitest";
import { getNativeBridge } from "../NativeBridge";
import {
  SMARTDESK_NATIVE_EVENT,
  subscribeNativeEvents,
  type SmartDeskNativeEvent,
} from "../nativeEvents";

afterEach(() => {
  Reflect.deleteProperty(window, "SmartDeskNative");
});

function envelope(
  type: string,
  data: unknown,
  eventId = "native-event-0001",
): SmartDeskNativeEvent {
  return {
    schemaVersion: 1,
    eventId,
    timestamp: 1_700_000_000_000,
    type,
    data,
  } as SmartDeskNativeEvent;
}

function installRequiredMethods(
  overrides: Partial<Window["SmartDeskNative"]> = {},
): void {
  Object.defineProperty(window, "SmartDeskNative", {
    configurable: true,
    value: {
      getDeviceInfo: vi.fn(),
      getDeviceCredential: vi.fn(() =>
        JSON.stringify(
          envelope("device_credential", {
            deviceToken: "device-secret-token-00000001",
          }),
        ),
      ),
      getIdentityStatus: vi.fn(() =>
        JSON.stringify(
          envelope("identity_status", { status: "IDLE" }),
        ),
      ),
      getRegisteredFaces: vi.fn(() =>
        JSON.stringify(
          envelope("registered_people", {
            personIds: [],
            count: 0,
          }),
        ),
      ),
      beginMaintenanceHold: vi.fn(),
      cancelMaintenanceHold: vi.fn(),
      startFaceVerification: vi.fn(),
      stopFaceVerification: vi.fn(),
      ...overrides,
    },
  });
}

describe("NativeBridge", () => {
  it("uses the browser adapter when Android native capability is absent", () => {
    expect(getNativeBridge().isAvailable()).toBe(false);
  });

  it("parses device information from SmartDeskNative", async () => {
    installRequiredMethods({
      getDeviceInfo: vi.fn(() =>
        JSON.stringify(
          envelope("device_info", {
            deviceId: "tablet-seat-01",
            seatId: 1,
            serverUrl: "http://host:8000",
            frontendUrl: "http://host:5173",
            configured: true,
          }),
        ),
      ),
    });

    await expect(getNativeBridge().getDeviceInfo()).resolves.toMatchObject({
      deviceId: "tablet-seat-01",
      seatId: 1,
      configured: true,
    });
  });

  it("forwards the immediate verification status through the unified event", async () => {
    const nativeEvent = vi.fn<(event: Event) => void>();
    const startFaceVerification = vi.fn(() =>
      JSON.stringify(
        envelope(
          "identity_status",
          { status: "VERIFYING" },
          "verification-start-0001",
        ),
      ),
    );
    window.addEventListener(SMARTDESK_NATIVE_EVENT, nativeEvent);
    installRequiredMethods({
      startFaceVerification,
    });

    await getNativeBridge().startFaceVerification("person-001");

    expect(nativeEvent).toHaveBeenCalledTimes(1);
    expect(startFaceVerification).toHaveBeenCalledWith("person-001");
    window.removeEventListener(SMARTDESK_NATIVE_EVENT, nativeEvent);
  });

  it("rejects an immediate native verification error after forwarding it", async () => {
    const nativeEvent = vi.fn<(event: Event) => void>();
    window.addEventListener(SMARTDESK_NATIVE_EVENT, nativeEvent);
    installRequiredMethods({
      startFaceVerification: vi.fn(() =>
        JSON.stringify(
          envelope("error", {
            code: "FACE_TEMPLATE_NOT_FOUND",
            message: "At least two people must be registered",
          }),
        ),
      ),
    });

    await expect(getNativeBridge().startFaceVerification("person-001")).rejects.toThrow(
      "FACE_TEMPLATE_NOT_FOUND: At least two people must be registered",
    );
    expect(nativeEvent).toHaveBeenCalledTimes(1);
    window.removeEventListener(SMARTDESK_NATIVE_EVENT, nativeEvent);
  });

  it("forwards maintenance hold start and cancellation", async () => {
    const beginMaintenanceHold = vi.fn();
    const cancelMaintenanceHold = vi.fn();
    installRequiredMethods({
      beginMaintenanceHold,
      cancelMaintenanceHold,
    });

    const bridge = getNativeBridge();
    await bridge.beginMaintenanceHold();
    await bridge.cancelMaintenanceHold();

    expect(beginMaintenanceHold).toHaveBeenCalledTimes(1);
    expect(cancelMaintenanceHold).toHaveBeenCalledTimes(1);
  });

  it("reports and forwards native microphone capture", async () => {
    const startMicrophoneCapture = vi.fn();
    const stopMicrophoneCapture = vi.fn();
    installRequiredMethods({
      startMicrophoneCapture,
      stopMicrophoneCapture,
    });

    const bridge = getNativeBridge();
    expect(bridge.supportsMicrophoneCapture()).toBe(true);
    await bridge.startMicrophoneCapture();
    await bridge.stopMicrophoneCapture();

    expect(startMicrophoneCapture).toHaveBeenCalledTimes(1);
    expect(stopMicrophoneCapture).toHaveBeenCalledTimes(1);
  });

  it("reads the credential and diagnostic native data", async () => {
    installRequiredMethods({
      getRegisteredFaces: vi.fn(() =>
        JSON.stringify(
          envelope("registered_people", {
            personIds: ["person_001"],
            count: 1,
          }),
        ),
      ),
    });

    const bridge = getNativeBridge();
    await expect(bridge.getDeviceCredential()).resolves.toBe(
      "device-secret-token-00000001",
    );
    await expect(bridge.getNativeStatus()).resolves.toMatchObject({
      status: "IDLE",
    });
    await expect(bridge.getRegisteredFaces()).resolves.toEqual({
      personIds: ["person_001"],
      count: 1,
    });
  });

  it("imports and removes a host-local face template", async () => {
    const importFacePhotos = vi.fn(() =>
      JSON.stringify(
        envelope("face_photo_import_result", {
          personId: "host-person",
          selectedCount: 5,
          acceptedCount: 5,
          usedCount: 5,
          saved: true,
          message: "主持人模板已保存",
          registeredPeople: ["host-person"],
        }),
      ),
    );
    const removeFaceTemplate = vi.fn(() =>
      JSON.stringify(
        envelope("identity_status", {
          status: "IDLE",
          message: "主持人模板已删除",
        }),
      ),
    );
    installRequiredMethods({ importFacePhotos, removeFaceTemplate });

    const bridge = getNativeBridge();
    await expect(
      bridge.importLocalFaceTemplate("host-person", "[]"),
    ).resolves.toMatchObject({ personId: "host-person", saved: true });
    await expect(
      bridge.removeLocalFaceTemplate("host-person"),
    ).resolves.toBeUndefined();

    expect(importFacePhotos).toHaveBeenCalledWith("host-person", "[]");
    expect(removeFaceTemplate).toHaveBeenCalledWith("host-person");
  });

  it("suppresses duplicate native event IDs", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeNativeEvents(listener);
    const event = envelope(
      "identity_status",
      { status: "VERIFIED" },
      "duplicate-event-0001",
    );

    window.dispatchEvent(
      new CustomEvent(SMARTDESK_NATIVE_EVENT, { detail: event }),
    );
    window.dispatchEvent(
      new CustomEvent(SMARTDESK_NATIVE_EVENT, { detail: event }),
    );

    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });
});
