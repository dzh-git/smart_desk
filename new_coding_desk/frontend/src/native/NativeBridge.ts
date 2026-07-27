import { AndroidNativeBridge, isAndroidNativeAvailable } from "./AndroidNativeBridge";
import { WebNativeBridge } from "./WebNativeBridge";

export interface DeviceInfo {
  deviceId: string;
  seatId: number | null;
  serverUrl: string | null;
  frontendUrl: string | null;
  configured: boolean;
  manufacturer?: string;
  model?: string;
  androidVersion?: string;
  sdkInt?: number;
  bridgeReady?: boolean;
}

export interface NativeBridge {
  isAvailable(): boolean;
  getDeviceInfo(): Promise<DeviceInfo>;
  startFaceVerification(): Promise<void>;
  stopFaceVerification(): Promise<void>;
}

export function getNativeBridge(): NativeBridge {
  return isAndroidNativeAvailable()
    ? new AndroidNativeBridge()
    : new WebNativeBridge();
}
