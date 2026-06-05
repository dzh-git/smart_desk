/**
 * SpeechWsClient — /ws/speech WebSocket client for PCM16 audio uplink.
 *
 * Protocol (docs/WEBSOCKET_PROTOCOL.md §3):
 *   Client connects → sends `start` → server replies `started` →
 *   client streams binary PCM16 frames → client sends `end_hint` or `cancel`.
 *
 * Lifecycle:
 *   const client = new SpeechWsClient();
 *   const { utteranceId, sessionKey } = await client.connect(meetingId, seatId);
 *   client.sendAudio(pcm16Frame);
 *   // ...
 *   client.sendEndHint();   // normal stop
 *   // or client.sendCancel();  // cancel mid-utterance
 *   client.close();
 *
 * Error handling:
 *   - Protocol errors (NOT_SPEAKER_SEAT, SPEECH_WS_NOT_STARTED, etc.)
 *     cause `connect()` to reject with a descriptive message.
 *   - Connection loss sets status to "disconnected".
 */

export type SpeechWsStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "started"
  | "error";

export interface StartResult {
  utteranceId: string;
  sessionKey: string;
}

export type SpeechWsStatusCallback = (
  status: SpeechWsStatus,
  error?: string,
) => void;

export type SpeechWsErrorCallback = (code: string, message: string) => void;

export class SpeechWsClient {
  private ws: WebSocket | null = null;
  private status: SpeechWsStatus = "disconnected";
  private statusCallback: SpeechWsStatusCallback | null = null;
  private errorCallback: SpeechWsErrorCallback | null = null;
  private resolveConnect: ((result: StartResult) => void) | null = null;
  private rejectConnect: ((err: Error) => void) | null = null;

  // ---- Configuration ----

  /**
   * Register a callback for status changes.
   * Called on every transition (connecting → connected → started → etc.).
   */
  onStatusChange(cb: SpeechWsStatusCallback): void {
    this.statusCallback = cb;
  }

  /**
   * Register a callback for protocol-level errors.
   * Called when the server sends {"type":"error","code":"...","message":"..."}.
   */
  onError(cb: SpeechWsErrorCallback): void {
    this.errorCallback = cb;
  }

  // ---- Connection ----

  /**
   * Connect to /ws/speech/{meeting_id}?seat={seat_id}, send `start`,
   * and wait for `started` response.
   *
   * @returns Promise that resolves with utterance_id and session_key.
   */
  connect(meetingId: number, seatId: number): Promise<StartResult> {
    return new Promise((resolve, reject) => {
      this.resolveConnect = resolve;
      this.rejectConnect = reject;

      this.setStatus("connecting");

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${window.location.host}/ws/speech/${meetingId}?seat=${seatId}`;

      const ws = new WebSocket(url);
      this.ws = ws;

      ws.onopen = () => {
        this.setStatus("connected");
        // Send start command immediately per protocol §3
        ws.send(
          JSON.stringify({
            type: "start",
            sample_rate: 16000,
            encoding: "pcm_s16le",
            channels: 1,
          }),
        );
      };

      ws.onmessage = (event: MessageEvent) => {
        // Binary messages are audio frames sent from server → client (none expected)
        if (event.data instanceof Blob || event.data instanceof ArrayBuffer) {
          return;
        }

        try {
          const msg = JSON.parse(event.data as string);

          if (msg.type === "started") {
            this.setStatus("started");
            this.resolveConnect?.({
              utteranceId: msg.utterance_id,
              sessionKey: msg.session_key,
            });
            this.resolveConnect = null;
            this.rejectConnect = null;
          } else if (msg.type === "error") {
            this.setStatus("error", msg.message ?? msg.code);
            this.errorCallback?.(msg.code, msg.message ?? "");
            this.rejectConnect?.(new Error(msg.message ?? msg.code));
            this.resolveConnect = null;
            this.rejectConnect = null;
          }
        } catch {
          // Ignore parse errors on binary or malformed messages
        }
      };

      ws.onclose = () => {
        this.ws = null;
        this.setStatus("disconnected");
        this.rejectConnect?.(new Error("WebSocket closed unexpectedly"));
        this.resolveConnect = null;
        this.rejectConnect = null;
      };

      ws.onerror = () => {
        this.setStatus("error", "WebSocket connection failed");
        this.rejectConnect?.(new Error("WebSocket connection failed"));
        this.resolveConnect = null;
        this.rejectConnect = null;
      };
    });
  }

  // ---- Send helpers ----

  /**
   * Send a PCM16 binary frame. Only valid after `started` status.
   */
  sendAudio(pcm16: ArrayBufferLike): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(pcm16);
    }
  }

  /**
   * Signal the end of the current utterance. The backend will finalize
   * via VAD + offline ASR rescore. After this the client should close
   * the connection or wait for further instructions.
   */
  sendEndHint(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "end_hint" }));
    }
  }

  /**
   * Cancel the current utterance immediately. The backend discards
   * buffered audio and does not persist. The client should close
   * the connection after sending cancel.
   */
  sendCancel(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "cancel" }));
    }
  }

  /** Get the current connection status. */
  get currentStatus(): SpeechWsStatus {
    return this.status;
  }

  // ---- Lifecycle ----

  /**
   * Close the WebSocket connection. Safe to call multiple times.
   */
  close(): void {
    if (this.ws) {
      // Prevent auto-reconnect if the library supports it
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.setStatus("disconnected");
    this.resolveConnect = null;
    this.rejectConnect = null;
  }

  // ---- Internal ----

  private setStatus(status: SpeechWsStatus, error?: string): void {
    this.status = status;
    this.statusCallback?.(status, error);
  }
}
