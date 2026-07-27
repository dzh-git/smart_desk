import type { DeviceInfo, NativeBridge } from "./NativeBridge";
import {
  dispatchNativeEvent,
  type SmartDeskNativeEvent,
} from "./nativeEvents";

interface SmartDeskNativeJavascriptInterface {
  getDeviceInfo(): string | object;
  startFaceVerification(): string | object | void;
  stopFaceVerification(): string | object | void;
}

declare global {
  interface Window {
    SmartDeskNative?: SmartDeskNativeJavascriptInterface;
  }
}

interface NativeEnvelope<T> {
  type: string;
  data: T;
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
  dispatchNativeEvent(parsePayload<SmartDeskNativeEvent>(payload));
}

export function isAndroidNativeAvailable(): boolean {
  return (
    typeof window.SmartDeskNative?.getDeviceInfo === "function" &&
    typeof window.SmartDeskNative?.startFaceVerification === "function" &&
    typeof window.SmartDeskNative?.stopFaceVerification === "function"
  );
}

export class AndroidNativeBridge implements NativeBridge {
  isAvailable(): boolean {
    return isAndroidNativeAvailable();
  }

  async getDeviceInfo(): Promise<DeviceInfo> {
    const envelope = parsePayload<NativeEnvelope<DeviceInfo>>(
      nativeInterface().getDeviceInfo(),
    );
    if (envelope.type !== "device_info" || !envelope.data) {
      throw new Error("SmartDeskNative returned invalid device information");
    }
    return envelope.data;
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
