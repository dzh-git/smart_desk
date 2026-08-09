import { getNativeBridge } from "../native/NativeBridge";
import { subscribeNativeEvents } from "../native/nativeEvents";
import type {
  AudioFrameCallback,
  MicrophoneErrorCallback,
} from "./microphone";

function decodeBase64Pcm16(value: string): ArrayBuffer {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

export function isAndroidNativeMicrophoneAvailable(): boolean {
  const bridge = getNativeBridge();
  return bridge.isAvailable() && bridge.supportsMicrophoneCapture();
}

export class AndroidNativeMicrophoneCapture {
  private active = false;
  private unsubscribe: (() => void) | null = null;
  private timeout: number | null = null;

  async start(
    onFrame: AudioFrameCallback,
    onError?: MicrophoneErrorCallback,
  ): Promise<void> {
    if (this.active) return;
    const bridge = getNativeBridge();
    if (!bridge.supportsMicrophoneCapture()) {
      throw new Error("Android native microphone capture is unavailable");
    }

    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const fail = (message: string) => {
        if (!settled) {
          settled = true;
          reject(new Error(message));
        } else {
          onError?.(message);
        }
      };

      this.unsubscribe = subscribeNativeEvents((event) => {
        if (event.type === "microphone_audio") {
          const data = event.data as { pcm16Base64?: string };
          if (this.active && typeof data.pcm16Base64 === "string") {
            onFrame(decodeBase64Pcm16(data.pcm16Base64));
          }
          return;
        }
        if (event.type === "microphone_status") {
          const data = event.data as { status?: string };
          if (data.status === "STARTED") {
            this.active = true;
            if (!settled) {
              settled = true;
              resolve();
            }
          } else if (data.status === "STOPPED") {
            this.active = false;
          }
          return;
        }
        if (event.type === "error") {
          const data = event.data as { code?: string; message?: string };
          if (data.code?.startsWith("MICROPHONE_")) {
            this.active = false;
            fail(data.message ?? data.code);
          }
        }
      });

      this.timeout = window.setTimeout(() => {
        fail("Android microphone capture start timed out");
      }, 10_000);

      bridge.startMicrophoneCapture().catch((error: unknown) => {
        fail(error instanceof Error ? error.message : String(error));
      });
    }).finally(() => {
      if (this.timeout !== null) {
        window.clearTimeout(this.timeout);
        this.timeout = null;
      }
    });
  }

  stop(): void {
    if (this.timeout !== null) {
      window.clearTimeout(this.timeout);
      this.timeout = null;
    }
    const bridge = getNativeBridge();
    if (bridge.supportsMicrophoneCapture()) {
      void bridge.stopMicrophoneCapture().catch(() => undefined);
    }
    this.active = false;
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  get isActive(): boolean {
    return this.active;
  }
}
