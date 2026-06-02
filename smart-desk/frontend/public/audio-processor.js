/**
 * AudioWorklet processor — captures raw Float32 PCM from mic.
 * Runs in dedicated audio thread, bypasses main-thread jank.
 * Batches 4096-sample chunks (~256ms @ 16kHz) before posting to main thread.
 * Avoids flooding the message port with 125 msg/sec from default 128-sample frames.
 */
const CHUNK = 4096

class AudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this._buf = new Float32Array(CHUNK)
    this._pos = 0
  }

  process(inputs) {
    const input = inputs[0]
    if (input && input.length > 0 && input[0]) {
      const data = input[0]
      for (let i = 0; i < data.length; i++) {
        this._buf[this._pos++] = data[i]
        if (this._pos >= CHUNK) {
          this.port.postMessage(new Float32Array(this._buf))
          this._buf = new Float32Array(CHUNK)
          this._pos = 0
        }
      }
    }
    return true
  }
}

registerProcessor('audio-processor', AudioProcessor)
