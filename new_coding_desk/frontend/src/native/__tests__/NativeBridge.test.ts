import { afterEach, describe, expect, it, vi } from "vitest";
import { getNativeBridge } from "../NativeBridge";
import {
  SMARTDESK_NATIVE_EVENT,
  type SmartDeskNativeEvent,
} from "../nativeEvents";

afterEach(() => {
  Reflect.deleteProperty(window, "SmartDeskNative");
});

describe("NativeBridge", () => {
  it("uses the browser adapter when Android native capability is absent", () => {
    expect(getNativeBridge().isAvailable()).toBe(false);
  });

  it("parses device information from SmartDeskNative", async () => {
    Object.defineProperty(window, "SmartDeskNative", {
      configurable: true,
      value: {
        getDeviceInfo: vi.fn(() =>
          JSON.stringify({
            type: "device_info",
            data: {
              deviceId: "tablet-seat-01",
              seatId: 1,
              serverUrl: "http://host:8000",
              frontendUrl: "http://host:5173",
              configured: true,
            },
          }),
        ),
        startFaceVerification: vi.fn(),
        stopFaceVerification: vi.fn(),
      },
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
    Object.defineProperty(window, "SmartDeskNative", {
      configurable: true,
      value: {
        getDeviceInfo: vi.fn(),
        startFaceVerification: vi.fn(() =>
          JSON.stringify({
            type: "identity_status",
            data: { status: "VERIFYING" },
          } satisfies SmartDeskNativeEvent),
        ),
        stopFaceVerification: vi.fn(),
      },
    });

    await getNativeBridge().startFaceVerification();

    expect(nativeEvent).toHaveBeenCalledTimes(1);
    window.removeEventListener(SMARTDESK_NATIVE_EVENT, nativeEvent);
  });
});
