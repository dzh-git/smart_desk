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
  maintenanceAccessAvailable?: boolean;
  appVersion?: string;
  manufacturer?: string;
  model?: string;
  androidVersion?: string;
  sdkInt?: number;
  bridgeReady?: boolean;
  cameraReady?: boolean;
  faceModelReady?: boolean;
  microphoneReady?: boolean;
  nativeMicrophoneCaptureAvailable?: boolean;
  nativeLastError?: string | null;
  identityMode?: "formal" | "debug";
}

export interface RegisteredFaces {
  personIds: string[];
  count: number;
}

export interface LocalFaceTemplateImportResult {
  personId: string;
  selectedCount: number;
  acceptedCount: number;
  usedCount: number;
  saved: boolean;
  message: string;
  registeredPeople: string[];
}

export interface CentralFaceTemplateResult {
  template: {
    personId: string;
    personName: string;
    modelVersion: string;
    modelHash: string;
    pipelineVersion: number;
    revision: number;
    createdAt: string;
    updatedAt: string;
  };
  evictedPersonId?: string | null;
  evictedPersonName?: string | null;
}

export interface FaceTemplateSyncResult {
  meetingId: number;
  templateSetRevision: number;
  templateCount: number;
  expectedPersonId: string;
  status: "SYNCED";
}

export interface NativeBridge {
  isAvailable(): boolean;
  getDeviceInfo(): Promise<DeviceInfo>;
  getDeviceCredential(): Promise<string>;
  getNativeStatus(): Promise<import("./nativeEvents").NativeIdentityStatus>;
  getRegisteredFaces(): Promise<RegisteredFaces>;
  beginMaintenanceHold(): Promise<void>;
  cancelMaintenanceHold(): Promise<void>;
  supportsMicrophoneCapture(): boolean;
  startMicrophoneCapture(): Promise<void>;
  stopMicrophoneCapture(): Promise<void>;
  startFaceVerification(personId: string): Promise<void>;
  stopFaceVerification(): Promise<void>;
  importLocalFaceTemplate(
    personId: string,
    photosJson: string,
  ): Promise<LocalFaceTemplateImportResult>;
  removeLocalFaceTemplate(personId: string): Promise<void>;
  applyProvisionalThreshold(
    value: number,
  ): Promise<import("./nativeEvents").NativeIdentityStatus>;
  publishCentralFaceTemplate(
    personId: string,
    photosJson: string,
  ): Promise<CentralFaceTemplateResult>;
  syncFaceTemplates(meetingId: number): Promise<FaceTemplateSyncResult>;
  openLocalDiagnostics(): Promise<void>;
  closeHostFaceTemplates(): Promise<void>;
}

export function getNativeBridge(): NativeBridge {
  return isAndroidNativeAvailable()
    ? new AndroidNativeBridge()
    : new WebNativeBridge();
}
