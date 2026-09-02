import { afterEach, describe, expect, it, vi } from "vitest";
import { AndroidNativeMicrophoneCapture } from "./androidNativeMicrophone";
import {
  SMARTDESK_NATIVE_EVENT,
  type SmartDeskNativeEvent,
} from "../native/nativeEvents";

afterEach(() => {
  Reflect.deleteProperty(window, "SmartDeskNative");
});

function dispatch(type: string, data: unknown, eventId: string): void {
  const event: SmartDeskNativeEvent = {
    schemaVersion: 1,
    eventId,
    timestamp: Date.now(),
    type,
    data,
  } as SmartDeskNativeEvent;
  window.dispatchEvent(
    new CustomEvent(SMARTDESK_NATIVE_EVENT, { detail: event }),
  );
}

describe("AndroidNativeMicrophoneCapture", () => {
  it("starts, decodes PCM16 frames, and stops through the native bridge", async () => {
    const startMicrophoneCapture = vi.fn();
    const stopMicrophoneCapture = vi.fn();
    Object.defineProperty(window, "SmartDeskNative", {
      configurable: true,
      value: {
        getDeviceInfo: vi.fn(),
        getDeviceCredential: vi.fn(),
        getIdentityStatus: vi.fn(),
        getRegisteredFaces: vi.fn(),
        startFaceVerification: vi.fn(),
        stopFaceVerification: vi.fn(),
        startMicrophoneCapture,
        stopMicrophoneCapture,
      },
    });

    const frames: Uint8Array[] = [];
    const capture = new AndroidNativeMicrophoneCapture();
    const started = capture.start((frame) => {
      frames.push(new Uint8Array(frame));
    });

    expect(startMicrophoneCapture).toHaveBeenCalledTimes(1);
    dispatch("microphone_status", { status: "STARTED" }, "mic-started");
    await started;
    expect(capture.isActive).toBe(true);

    dispatch(
      "microphone_audio",
      { pcm16Base64: "AQIDBA==" },
      "mic-frame-1",
    );
    expect(Array.from(frames[0])).toEqual([1, 2, 3, 4]);

    capture.stop();
    expect(stopMicrophoneCapture).toHaveBeenCalledTimes(1);
    expect(capture.isActive).toBe(false);
  });
});
