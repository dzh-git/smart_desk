import type {
  DeviceInfo,
  NativeBridge,
  RegisteredFaces,
} from "./NativeBridge";
import type { NativeIdentityStatus } from "./nativeEvents";

export class WebNativeBridge implements NativeBridge {
  isAvailable(): boolean {
    return false;
  }

  async getDeviceInfo(): Promise<DeviceInfo> {
    return {
      deviceId: "web-browser",
      seatId: null,
      serverUrl: null,
      frontendUrl: window.location.origin,
      configured: false,
      bridgeReady: false,
    };
  }

  async getDeviceCredential(): Promise<string> {
    throw new Error("Android device credential is unavailable");
  }

  async getNativeStatus(): Promise<NativeIdentityStatus> {
    return {
      status: "UNAVAILABLE",
      verificationLevel: "NONE",
      message: "Android native face verification is unavailable",
    };
  }

  async getRegisteredFaces(): Promise<RegisteredFaces> {
    return { personIds: [], count: 0 };
  }

  async beginMaintenanceHold(): Promise<void> {
    throw new Error("Android maintenance access is unavailable");
  }

  async cancelMaintenanceHold(): Promise<void> {
    // Browser debugging has no native maintenance hold to cancel.
  }

  supportsMicrophoneCapture(): boolean {
    return false;
  }

  async startMicrophoneCapture(): Promise<void> {
    throw new Error("Android native microphone capture is unavailable");
  }

  async stopMicrophoneCapture(): Promise<void> {
    // Browser capture is owned by MicrophoneCapture.
  }

  async startFaceVerification(): Promise<void> {
    throw new Error("Android native face verification is unavailable");
  }

  async stopFaceVerification(): Promise<void> {
    // Browser debugging has no native camera session to stop.
  }
}
