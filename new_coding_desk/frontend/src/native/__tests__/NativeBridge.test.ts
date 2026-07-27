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
    window.addEventListener(SMARTDESK_NATIVE_EVENT, nativeEvent);
    installRequiredMethods({
      startFaceVerification: vi.fn(() =>
        JSON.stringify(
          envelope(
            "identity_status",
            { status: "VERIFYING" },
            "verification-start-0001",
          ),
        ),
      ),
    });

    await getNativeBridge().startFaceVerification();

    expect(nativeEvent).toHaveBeenCalledTimes(1);
    window.removeEventListener(SMARTDESK_NATIVE_EVENT, nativeEvent);
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
