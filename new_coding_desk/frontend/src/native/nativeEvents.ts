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
  threshold?: number | null;
  stageSampleCount?: number;
  stageRequiredSamples?: number;
  matchStreak?: number;
  registeredCount?: number;
  thresholdStatus?: string;
  verificationLevel?: string;
  modelVersion?: string | null;
  message?: string;
  timestamp?: number;
}

export interface NativeEventEnvelope {
  schemaVersion: number;
  eventId: string;
  timestamp: number;
}

export type SmartDeskNativeEvent = NativeEventEnvelope &
  (
    | { type: "identity_status"; data: NativeIdentityStatus }
    | { type: "host_console_access"; data: { granted: boolean; pending: boolean; message?: string } }
    | { type: "host_identity"; data: { defaultPersonId: string | null; registeredPersonIds: string[] } }
    | { type: "camera_status"; data: Record<string, unknown> }
    | { type: "face_detection_status"; data: Record<string, unknown> }
    | {
        type: "app_lifecycle";
        data: { state?: string; reason?: string };
      }
    | { type: "error"; data: { code?: string; message?: string } }
    | { type: string; data: unknown }
  );

function legacyEventId(type: string): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return `legacy:${globalThis.crypto.randomUUID()}`;
  }
  return `legacy:${type}:${Date.now()}:${Math.random()}`;
}

export function normalizeNativeEvent(
  value: unknown,
): SmartDeskNativeEvent {
  if (!value || typeof value !== "object") {
    throw new Error("SmartDeskNative returned an invalid event");
  }
  const candidate = value as Partial<SmartDeskNativeEvent>;
  if (typeof candidate.type !== "string" || !("data" in candidate)) {
    throw new Error("SmartDeskNative returned an invalid event");
  }
  return {
    schemaVersion:
      typeof candidate.schemaVersion === "number"
        ? candidate.schemaVersion
        : 0,
    eventId:
      typeof candidate.eventId === "string" && candidate.eventId
        ? candidate.eventId
        : legacyEventId(candidate.type),
    timestamp:
      typeof candidate.timestamp === "number"
        ? candidate.timestamp
        : Date.now(),
    type: candidate.type,
    data: candidate.data,
  } as SmartDeskNativeEvent;
}

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
  const deliveredEventIds = new Set<string>();
  const handler = (event: Event) => {
    try {
      const detail = normalizeNativeEvent(
        (event as CustomEvent<unknown>).detail,
      );
      if (deliveredEventIds.has(detail.eventId)) return;
      deliveredEventIds.add(detail.eventId);
      if (deliveredEventIds.size > 256) {
        const oldest = deliveredEventIds.values().next().value;
        if (oldest) deliveredEventIds.delete(oldest);
      }
      listener(detail);
    } catch {
      // Ignore malformed events from unrelated or stale bridge versions.
    }
  };

  window.addEventListener(SMARTDESK_NATIVE_EVENT, handler);
  return () => {
    window.removeEventListener(SMARTDESK_NATIVE_EVENT, handler);
  };
}
