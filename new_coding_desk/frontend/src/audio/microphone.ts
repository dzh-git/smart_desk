/**
 * MicrophoneCapture — browser microphone → 16 kHz mono PCM16 s16le.
 *
 * Architecture:
 *   getUserMedia → MediaStream → AudioContext (16 kHz) → ScriptProcessorNode
 *   → onaudioprocess callback → float32 → int16 → 100 ms frames delivered
 *     via onFrame callback.
 *
 * Frame size: 1600 samples (100 ms @ 16 kHz) → 3200 bytes PCM16.
 *
 * Lifecycle:
 *   const mic = new MicrophoneCapture();
 *   await mic.start(onFrame, onError);
 *   // ... recording ...
 *   mic.stop();  // stops tracks, disconnects nodes, closes AudioContext
 *
 * Thread safety: all AudioContext callbacks are on the audio thread.
 * The onFrame callback is called from the audio processing graph.
 */

import { trace } from "./speechTrace";

export type AudioFrameCallback = (pcm16: ArrayBufferLike) => void;
export type MicrophoneErrorCallback = (error: string) => void;

export class MicrophoneCapture {
  private stream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private processorNode: ScriptProcessorNode | null = null;
  private frameCallback: AudioFrameCallback | null = null;
  private errorCallback: MicrophoneErrorCallback | null = null;

  /** Target sample rate (16 kHz per WEBSOCKET_PROTOCOL §3). */
  private readonly targetSampleRate = 16000;

  /** Duration per frame in milliseconds. */
  private readonly frameDurationMs = 100;

  /** Number of PCM16 samples per frame. */
  private readonly samplesPerFrame: number;

  /** Buffer for partial frames between onaudioprocess calls. */
  private partialBuffer: Float32Array[] = [];

  constructor() {
    this.samplesPerFrame = Math.floor(
      (this.targetSampleRate * this.frameDurationMs) / 1000,
    );
  }

  /**
   * Request microphone access and start capture.
   *
   * @param onFrame  Called with each complete PCM16 frame (ArrayBuffer).
   * @param onError  Called on audio processing errors.
   */
  async start(
    onFrame: AudioFrameCallback,
    onError?: MicrophoneErrorCallback,
  ): Promise<void> {
    this.frameCallback = onFrame;
    this.errorCallback = onError ?? null;
    this.partialBuffer = [];

    // 1. Request microphone
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      throw new Error(
        `Microphone access denied: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    this.stream = stream;

    // 2. Create AudioContext at target sample rate.
    //    If the hardware does not support 16 kHz the browser picks the
    //    closest available rate; frames are still chunked correctly.
    const ctx = new AudioContext({ sampleRate: this.targetSampleRate });
    this.audioContext = ctx;

    // 3. Create source node from the mic stream.
    const source = ctx.createMediaStreamSource(stream);
    this.sourceNode = source;

    // 4. ScriptProcessorNode for frame-level audio access.
    //    bufferSize 4096 is a safe default across browsers (~256 ms @ 16 kHz).
    const processor = ctx.createScriptProcessor(4096, 1, 1);
    this.processorNode = processor;

    processor.onaudioprocess = (event: AudioProcessingEvent) => {
      try {
        const input = event.inputBuffer.getChannelData(0); // Float32Array
        this.processAudioInput(input);
      } catch (err) {
        this.errorCallback?.(
          `Audio processing error: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    };

    // 5. Connect the graph: source → processor → destination
    source.connect(processor);
    processor.connect(ctx.destination);

    trace("microphone_started_at", {});
  }

  /**
   * Process incoming Float32Array audio data, buffer partial frames,
   * and emit complete 100ms PCM16 frames via the callback.
   */
  private processAudioInput(input: Float32Array): void {
    // Store the new chunk
    this.partialBuffer.push(new Float32Array(input));

    // Total samples accumulated
    const totalSamples = this.partialBuffer.reduce(
      (sum, buf) => sum + buf.length,
      0,
    );
    if (totalSamples < this.samplesPerFrame) return;

    // Concatenate into a single Float32Array
    const combined = new Float32Array(totalSamples);
    let offset = 0;
    for (const buf of this.partialBuffer) {
      combined.set(buf, offset);
      offset += buf.length;
    }
    this.partialBuffer = [];

    // Emit complete frames, keep remainder for next callback
    let pos = 0;
    while (pos + this.samplesPerFrame <= combined.length) {
      const frame = combined.subarray(pos, pos + this.samplesPerFrame);
      const pcm16 = MicrophoneCapture.float32ToPcm16(frame);
      trace("frontend_pcm_created_at", { frameIndex: pos / this.samplesPerFrame });
      this.frameCallback?.(pcm16.buffer);
      pos += this.samplesPerFrame;
    }

    // Keep leftover samples for the next onaudioprocess call
    if (pos < combined.length) {
      this.partialBuffer.push(
        new Float32Array(combined.subarray(pos)),
      );
    }
  }

  /**
   * Convert a Float32Array (range [-1, 1]) to PCM16 s16le Int16Array.
   */
  static float32ToPcm16(float32: Float32Array): Int16Array {
    const pcm16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const clamped = Math.max(-1, Math.min(1, float32[i]));
      // int16 range: -32768 .. 32767
      pcm16[i] = clamped < 0
        ? Math.round(clamped * 0x8000)
        : Math.round(clamped * 0x7fff);
    }
    return pcm16;
  }

  /**
   * Stop capture: stop all tracks, disconnect audio graph, close context.
   * Safe to call multiple times.
   */
  stop(): void {
    this.frameCallback = null;
    this.errorCallback = null;
    this.partialBuffer = [];

    // Disconnect and clear processor
    if (this.processorNode) {
      this.processorNode.disconnect();
      this.processorNode = null;
    }

    // Disconnect and clear source
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }

    // Close AudioContext
    if (this.audioContext) {
      this.audioContext.close().catch(() => {
        // Ignore close errors (context may already be closed)
      });
      this.audioContext = null;
    }

    // Stop all media tracks
    if (this.stream) {
      for (const track of this.stream.getTracks()) {
        track.stop();
      }
      this.stream = null;
    }
  }

  /** True when microphone is actively capturing. */
  get isActive(): boolean {
    return this.stream?.active === true && this.audioContext?.state === "running";
  }
}
