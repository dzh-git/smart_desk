import type { DeviceInfo, NativeBridge } from "./NativeBridge";

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

  async startFaceVerification(): Promise<void> {
    throw new Error("Android native face verification is unavailable");
  }

  async stopFaceVerification(): Promise<void> {
    // Browser debugging has no native camera session to stop.
  }
}
