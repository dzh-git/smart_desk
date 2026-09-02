import type {
  DeviceInfo,
  NativeBridge,
  RegisteredFaces,
  CentralFaceTemplateResult,
  FaceTemplateSyncResult,
  LocalFaceTemplateImportResult,
  HostConsoleAccess,
  HostIdentityProfile,
} from "./NativeBridge";
import {
  dispatchNativeEvent,
  normalizeNativeEvent,
  type NativeIdentityStatus,
  type SmartDeskNativeEvent,
} from "./nativeEvents";

interface SmartDeskNativeJavascriptInterface {
  getDeviceInfo(): string | object;
  getDeviceCredential(): string | object;
  getIdentityStatus(): string | object;
  getRegisteredFaces(): string | object;
  getHostConsoleAccess?(): string | object;
  requestHostConsoleAccess?(): string | object;
  getDefaultHostIdentity?(): string | object;
  setDefaultHostIdentity?(personId: string | null): string | object;
  beginMaintenanceHold?(): void;
  cancelMaintenanceHold?(): void;
  startMicrophoneCapture?(): void;
  stopMicrophoneCapture?(): void;
  startFaceVerification(personId: string): string | object | void;
  stopFaceVerification(): string | object | void;
  importFacePhotos?(personId: string, photosJson: string): string | object;
  removeFaceTemplate?(personId: string): string | object;
  applyProvisionalThreshold?(value: number): string | object;
  publishCentralFaceTemplate?(personId: string, photosJson: string): string | object;
  syncFaceTemplates?(meetingId: number): string | object;
  openLocalDiagnostics?(): void;
  closeHostFaceTemplates?(): void;
}

declare global {
  interface Window {
    SmartDeskNative?: SmartDeskNativeJavascriptInterface;
  }
}

function nativeInterface(): SmartDeskNativeJavascriptInterface {
  if (!window.SmartDeskNative) {
    throw new Error("SmartDeskNative Bridge unavailable");
  }
  return window.SmartDeskNative;
}

function parsePayload<T>(payload: string | object): T {
  return (
    typeof payload === "string" ? JSON.parse(payload) : payload
  ) as T;
}

function dispatchImmediateResult(payload: string | object | void): void {
  if (payload == null) return;
  const envelope = normalizeNativeEvent(
    parsePayload<SmartDeskNativeEvent>(payload),
  );
  dispatchNativeEvent(envelope);
  if (envelope.type === "error") {
    const error = envelope.data as { code?: string; message?: string };
    throw new Error(
      [error.code, error.message].filter(Boolean).join(": ") ||
        "SmartDeskNative operation failed",
    );
  }
}

function parseEnvelope<T>(
  payload: string | object,
  expectedType: string,
): T {
  const envelope = normalizeNativeEvent(parsePayload(payload));
  if (envelope.type === "error") {
    const error = envelope.data as { code?: string; message?: string };
    throw new Error(
      [error.code, error.message].filter(Boolean).join(": ") ||
        "SmartDeskNative operation failed",
    );
  }
  if (envelope.type !== expectedType || envelope.data == null) {
    throw new Error(
      `SmartDeskNative returned invalid ${expectedType} data`,
    );
  }
  return envelope.data as T;
}

export function isAndroidNativeAvailable(): boolean {
  return (
    typeof window.SmartDeskNative?.getDeviceInfo === "function" &&
    typeof window.SmartDeskNative?.getDeviceCredential === "function" &&
    typeof window.SmartDeskNative?.getIdentityStatus === "function" &&
    typeof window.SmartDeskNative?.getRegisteredFaces === "function" &&
    typeof window.SmartDeskNative?.startFaceVerification === "function" &&
    typeof window.SmartDeskNative?.stopFaceVerification === "function"
  );
}

export class AndroidNativeBridge implements NativeBridge {
  isAvailable(): boolean {
    return isAndroidNativeAvailable();
  }

  async getDeviceInfo(): Promise<DeviceInfo> {
    return parseEnvelope<DeviceInfo>(
      nativeInterface().getDeviceInfo(),
      "device_info",
    );
  }

  async getDeviceCredential(): Promise<string> {
    const data = parseEnvelope<{ deviceToken?: string }>(
      nativeInterface().getDeviceCredential(),
      "device_credential",
    );
    if (!data.deviceToken) {
      throw new Error("SmartDeskNative returned an empty device credential");
    }
    return data.deviceToken;
  }

  async getNativeStatus(): Promise<NativeIdentityStatus> {
    return parseEnvelope<NativeIdentityStatus>(
      nativeInterface().getIdentityStatus(),
      "identity_status",
    );
  }

  async getRegisteredFaces(): Promise<RegisteredFaces> {
    return parseEnvelope<RegisteredFaces>(
      nativeInterface().getRegisteredFaces(),
      "registered_people",
    );
  }

  async getHostConsoleAccess(): Promise<HostConsoleAccess> {
    const bridge = nativeInterface();
    if (typeof bridge.getHostConsoleAccess !== "function") {
      throw new Error("当前平板版本不支持主持人控制台解锁");
    }
    return parseEnvelope<HostConsoleAccess>(
      bridge.getHostConsoleAccess(),
      "host_console_access",
    );
  }

  async requestHostConsoleAccess(): Promise<HostConsoleAccess> {
    const bridge = nativeInterface();
    if (typeof bridge.requestHostConsoleAccess !== "function") {
      throw new Error("当前平板版本不支持主持人控制台解锁");
    }
    return parseEnvelope<HostConsoleAccess>(
      bridge.requestHostConsoleAccess(),
      "host_console_access",
    );
  }

  async getDefaultHostIdentity(): Promise<HostIdentityProfile> {
    const bridge = nativeInterface();
    if (typeof bridge.getDefaultHostIdentity !== "function") {
      throw new Error("当前平板版本不支持默认主持人身份");
    }
    return parseEnvelope<HostIdentityProfile>(
      bridge.getDefaultHostIdentity(),
      "host_identity",
    );
  }

  async setDefaultHostIdentity(personId: string | null): Promise<HostIdentityProfile> {
    const bridge = nativeInterface();
    if (typeof bridge.setDefaultHostIdentity !== "function") {
      throw new Error("当前平板版本不支持默认主持人身份");
    }
    return parseEnvelope<HostIdentityProfile>(
      bridge.setDefaultHostIdentity(personId),
      "host_identity",
    );
  }

  async beginMaintenanceHold(): Promise<void> {
    const bridge = nativeInterface();
    if (typeof bridge.beginMaintenanceHold !== "function") {
      throw new Error("SmartDeskNative maintenance access is unavailable");
    }
    bridge.beginMaintenanceHold();
  }

  async cancelMaintenanceHold(): Promise<void> {
    const bridge = nativeInterface();
    if (typeof bridge.cancelMaintenanceHold !== "function") return;
    bridge.cancelMaintenanceHold();
  }

  supportsMicrophoneCapture(): boolean {
    const bridge = nativeInterface();
    return typeof bridge.startMicrophoneCapture === "function" &&
      typeof bridge.stopMicrophoneCapture === "function";
  }

  async startMicrophoneCapture(): Promise<void> {
    const bridge = nativeInterface();
    if (typeof bridge.startMicrophoneCapture !== "function") {
      throw new Error("SmartDeskNative microphone capture is unavailable");
    }
    bridge.startMicrophoneCapture();
  }

  async stopMicrophoneCapture(): Promise<void> {
    const bridge = nativeInterface();
    bridge.stopMicrophoneCapture?.();
  }

  async startFaceVerification(personId: string): Promise<void> {
    dispatchImmediateResult(
      nativeInterface().startFaceVerification(personId),
    );
  }

  async stopFaceVerification(): Promise<void> {
    dispatchImmediateResult(
      nativeInterface().stopFaceVerification(),
    );
  }

  async importLocalFaceTemplate(
    personId: string,
    photosJson: string,
  ): Promise<LocalFaceTemplateImportResult> {
    const bridge = nativeInterface();
    if (typeof bridge.importFacePhotos !== "function") {
      throw new Error("当前平板版本不支持主持人本机模板管理");
    }
    return parseEnvelope<LocalFaceTemplateImportResult>(
      bridge.importFacePhotos(personId, photosJson),
      "face_photo_import_result",
    );
  }

  async removeLocalFaceTemplate(personId: string): Promise<void> {
    const bridge = nativeInterface();
    if (typeof bridge.removeFaceTemplate !== "function") {
      throw new Error("当前平板版本不支持删除主持人本机模板");
    }
    dispatchImmediateResult(bridge.removeFaceTemplate(personId));
  }

  async applyProvisionalThreshold(value: number): Promise<NativeIdentityStatus> {
    const bridge = nativeInterface();
    if (typeof bridge.applyProvisionalThreshold !== "function") {
      throw new Error("当前平板版本不支持主持人确认原型阈值");
    }
    return parseEnvelope<NativeIdentityStatus>(
      bridge.applyProvisionalThreshold(value),
      "identity_status",
    );
  }

  async publishCentralFaceTemplate(
    personId: string,
    photosJson: string,
  ): Promise<CentralFaceTemplateResult> {
    const bridge = nativeInterface();
    if (typeof bridge.publishCentralFaceTemplate !== "function") {
      throw new Error("当前平板版本不支持集中人脸模板管理");
    }
    return parseEnvelope<CentralFaceTemplateResult>(
      bridge.publishCentralFaceTemplate(personId, photosJson),
      "central_face_template_result",
    );
  }

  async syncFaceTemplates(meetingId: number): Promise<FaceTemplateSyncResult> {
    const bridge = nativeInterface();
    if (typeof bridge.syncFaceTemplates !== "function") {
      throw new Error("当前平板版本不支持会议人脸模板同步");
    }
    return parseEnvelope<FaceTemplateSyncResult>(
      bridge.syncFaceTemplates(meetingId),
      "face_template_sync",
    );
  }

  async openLocalDiagnostics(): Promise<void> {
    const bridge = nativeInterface();
    if (typeof bridge.openLocalDiagnostics !== "function") {
      throw new Error("当前平板版本不支持本地诊断入口");
    }
    bridge.openLocalDiagnostics();
  }

  async closeHostFaceTemplates(): Promise<void> {
    const bridge = nativeInterface();
    if (typeof bridge.closeHostFaceTemplates !== "function") {
      throw new Error("当前平板版本不支持关闭模板管理页");
    }
    bridge.closeHostFaceTemplates();
  }
}
