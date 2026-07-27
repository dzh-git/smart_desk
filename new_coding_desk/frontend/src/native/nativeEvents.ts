export const SMARTDESK_NATIVE_EVENT = "smartdesk-native-event";

export interface NativeIdentityStatus {
  mode?: string;
  status: string;
  personId?: string | null;
  similarity?: number | null;
  top1PersonId?: string | null;
  top1Score?: number | null;
  top2PersonId?: string | null;
  top2Score?: number | null;
  margin?: number | null;
  thresholdStatus?: string;
  verificationLevel?: string;
  modelVersion?: string | null;
  message?: string;
  timestamp?: number;
}

export type SmartDeskNativeEvent =
  | { type: "identity_status"; data: NativeIdentityStatus }
  | { type: "camera_status"; data: Record<string, unknown> }
  | { type: "face_detection_status"; data: Record<string, unknown> }
  | { type: "error"; data: { code?: string; message?: string } }
  | { type: string; data: unknown };

export function dispatchNativeEvent(event: SmartDeskNativeEvent): void {
  window.dispatchEvent(
    new CustomEvent<SmartDeskNativeEvent>(SMARTDESK_NATIVE_EVENT, {
      detail: event,
    }),
  );
}

export function subscribeNativeEvents(
  listener: (event: SmartDeskNativeEvent) => void,
): () => void {
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<SmartDeskNativeEvent>).detail;
    if (detail && typeof detail.type === "string") {
      listener(detail);
    }
  };

  window.addEventListener(SMARTDESK_NATIVE_EVENT, handler);
  return () => {
    window.removeEventListener(SMARTDESK_NATIVE_EVENT, handler);
  };
}
