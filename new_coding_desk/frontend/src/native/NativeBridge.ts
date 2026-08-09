import { AndroidNativeBridge, isAndroidNativeAvailable } from "./AndroidNativeBridge";
import { WebNativeBridge } from "./WebNativeBridge";

export interface DeviceInfo {
  deviceId: string;
  seatId: number | null;
  seatAlias?: string | null;
  centralHost?: string | null;
  serverUrl: string | null;
  frontendUrl: string | null;
  serverBaseUrl?: string | null;
  frontendBaseUrl?: string | null;
  configured: boolean;
  deviceTokenConfigured?: boolean;
  maintenancePinConfigured?: boolean;
  appVersion?: string;
  manufacturer?: string;
  model?: string;
  androidVersion?: string;
  sdkInt?: number;
  bridgeReady?: boolean;
  cameraReady?: boolean;
  faceModelReady?: boolean;
  microphoneReady?: boolean;
  nativeLastError?: string | null;
}

export interface RegisteredFaces {
  personIds: string[];
  count: number;
}

export interface NativeBridge {
  isAvailable(): boolean;
  getDeviceInfo(): Promise<DeviceInfo>;
  getDeviceCredential(): Promise<string>;
  getNativeStatus(): Promise<import("./nativeEvents").NativeIdentityStatus>;
  getRegisteredFaces(): Promise<RegisteredFaces>;
  startFaceVerification(): Promise<void>;
  stopFaceVerification(): Promise<void>;
}

export function getNativeBridge(): NativeBridge {
  return isAndroidNativeAvailable()
    ? new AndroidNativeBridge()
    : new WebNativeBridge();
}
