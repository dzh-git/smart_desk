import type {
  CentralFaceTemplateResult,
  DeviceInfo,
  FaceTemplateSyncResult,
  LocalFaceTemplateImportResult,
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

  async startFaceVerification(_personId: string): Promise<void> {
    throw new Error("Android native face verification is unavailable");
  }

  async stopFaceVerification(): Promise<void> {
    // Browser debugging has no native camera session to stop.
  }

  async importLocalFaceTemplate(
    _personId: string,
    _photosJson: string,
  ): Promise<LocalFaceTemplateImportResult> {
    throw new Error("主持人本机模板管理只能在 Android 平板使用");
  }

  async removeLocalFaceTemplate(_personId: string): Promise<void> {
    throw new Error("主持人本机模板管理只能在 Android 平板使用");
  }

  async applyProvisionalThreshold(
    _value: number,
  ): Promise<NativeIdentityStatus> {
    throw new Error("原型阈值只能在主持人 Android 平板确认");
  }

  async publishCentralFaceTemplate(
    _personId: string,
    _photosJson: string,
  ): Promise<CentralFaceTemplateResult> {
    throw new Error("集中人脸模板管理只能在主持人 Android 平板使用");
  }

  async syncFaceTemplates(_meetingId: number): Promise<FaceTemplateSyncResult> {
    throw new Error("会议人脸模板同步只能在参会者 Android 平板使用");
  }

  async openLocalDiagnostics(): Promise<void> {
    throw new Error("本地诊断只能在 Android 平板使用");
  }

  async closeHostFaceTemplates(): Promise<void> {
    throw new Error("模板管理页只能在主持人 Android 平板使用");
  }
}
