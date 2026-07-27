import type {
  DeviceInfo,
  NativeBridge,
  RegisteredFaces,
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
  startFaceVerification(): string | object | void;
  stopFaceVerification(): string | object | void;
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
  dispatchNativeEvent(
    normalizeNativeEvent(parsePayload<SmartDeskNativeEvent>(payload)),
  );
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

  async startFaceVerification(): Promise<void> {
    dispatchImmediateResult(
      nativeInterface().startFaceVerification(),
    );
  }

  async stopFaceVerification(): Promise<void> {
    dispatchImmediateResult(
      nativeInterface().stopFaceVerification(),
    );
  }
}
