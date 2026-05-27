import { ref, reactive } from 'vue'
import { api } from '../api/index.js'

const VAD_FRAME_MS = 30  // Silero VAD frame duration at 16kHz
const MAX_RECORDING_SEC = 25  // force-send if VAD doesn't detect silence within this
const INTERIM_INTERVAL_MS = 3000  // interim upload interval

/**
 * VAD-based audio recording + STT/translation upload.
 * Calls onInterim / onFinal callbacks with results.
 *
 * VAD tuned for meeting speech: ~1.8s silence gap to end utterance,
 * max 25s recording before auto-finalize.
 */
export function useAudioRecorder({ meetingId, seatId, onInterim, onFinal, onError }) {
  const isRecording = ref(false)
  const errorMsg = ref('')
  const interimItem = reactive({ zh: '', en: '' })
  const _rawChunks = []
  let _vadStopped = false
  let _audioCtx = null
  let _audioStream = null
  let _interimTimer = null
  let _interimPending = false
  let _myvad = null
  let _recordingStartedAt = 0

  function concatFloat32(chunks) {
    const len = chunks.reduce((s, c) => s + c.length, 0)
    const out = new Float32Array(len)
    let off = 0
    for (const c of chunks) { out.set(c, off); off += c.length }
    return out
  }

  function float32ToWav(float32, sampleRate = 16000) {
    const len = float32.length
    const buf = new ArrayBuffer(44 + len * 2)
    const v = new DataView(buf)
    const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)) }
    w(0, 'RIFF'); v.setUint32(4, 36 + len * 2, true); w(8, 'WAVE')
    w(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true)
    v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true)
    v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true)
    v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, len * 2, true)
    let o = 44
    for (let i = 0; i < len; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]))
      v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7FFF, true)
      o += 2
    }
    return new Blob([buf], { type: 'audio/wav' })
  }

  function accumulatedDurationSec() {
    const totalSamples = _rawChunks.reduce((s, c) => s + c.length, 0)
    return totalSamples / 16000
  }

  async function sendInterim() {
    if (_vadStopped || _interimPending || !_rawChunks.length) return
    const fullAudio = concatFloat32(_rawChunks)
    if (fullAudio.length < 16000) return  // at least 1s of audio for interim
    _interimPending = true
    try {
      const r = await api.uploadAudio(meetingId.value, seatId.value, float32ToWav(fullAudio), false)
      if (r.zh && r.zh !== '[无法识别语音]') {
        interimItem.zh = r.zh
        interimItem.en = r.en || ''
        onInterim && onInterim(r.zh, r.en || '')
      }
    } catch { /* ignore */ }
    finally { _interimPending = false }
  }

  async function finalizeUtterance(vadAudio) {
    _interimPending = false
    const wavBlob = float32ToWav(vadAudio)
    try {
      const r = await api.uploadAudio(meetingId.value, seatId.value, wavBlob, true)
      if (r.zh && r.zh !== '[无法识别语音]') {
        onFinal && onFinal(r.zh, r.en, r.seat_id || seatId.value)
      }
    } catch (e) {
      errorMsg.value = '语音识别失败: ' + e.message
      onError && onError(e.message)
    }
    interimItem.zh = ''
    interimItem.en = ''
    _rawChunks.length = 0
    _recordingStartedAt = 0
  }

  /** Force-finalize: concatenate all accumulated raw audio and send as final. */
  async function forceFinalize() {
    if (_vadStopped || !_rawChunks.length) return
    _interimPending = false
    const fullAudio = concatFloat32(_rawChunks)
    if (fullAudio.length < 16000) return
    try {
      const r = await api.uploadAudio(meetingId.value, seatId.value, float32ToWav(fullAudio), true)
      if (r.zh && r.zh !== '[无法识别语音]') {
        onFinal && onFinal(r.zh, r.en, r.seat_id || seatId.value)
      }
    } catch (e) {
      errorMsg.value = '语音识别失败: ' + e.message
      onError && onError(e.message)
    }
    // Reset accumulated audio but keep recording
    _rawChunks.length = 0
    _recordingStartedAt = Date.now()
    interimItem.zh = ''
    interimItem.en = ''
  }

  async function startRecording() {
    try {
      _vadStopped = false
      _rawChunks.length = 0
      _interimPending = false
      _recordingStartedAt = Date.now()
      interimItem.zh = ''
      interimItem.en = ''
      errorMsg.value = ''

      _myvad = await vad.MicVAD.new({
        onSpeechStart: () => {},
        onSpeechEnd: (audio) => {
          if (_vadStopped) return
          finalizeUtterance(audio)
        },
        onVADMisfire: () => {},
        // ~1.8s silence gap to end utterance (60 × 30ms)
        redemptionFrames: 60,
        preSpeechPadFrames: 20,
        // minimum ~360ms of speech to trigger (12 × 30ms)
        minSpeechFrames: 12,
        positiveSpeechThreshold: 0.55,
        negativeSpeechThreshold: 0.4,
        onnxWASMBasePath: 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/',
        baseAssetPath: 'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/',
      })
      _myvad.start()

      _audioStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      _audioCtx = new AudioContext({ sampleRate: 16000 })
      const source = _audioCtx.createMediaStreamSource(_audioStream)
      const processor = _audioCtx.createScriptProcessor(4096, 1, 1)
      processor.onaudioprocess = (e) => {
        if (_vadStopped) return
        _rawChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
        // Max recording duration safety: auto-finalize if VAD didn't detect silence
        if (_recordingStartedAt && accumulatedDurationSec() >= MAX_RECORDING_SEC) {
          forceFinalize()
        }
      }
      source.connect(processor)
      processor.connect(_audioCtx.destination)

      _interimTimer = setInterval(sendInterim, INTERIM_INTERVAL_MS)
      isRecording.value = true
    } catch (e) {
      if (e.name === 'NotAllowedError') {
        errorMsg.value = '麦克风权限被拒绝，请在浏览器设置中允许'
      } else {
        errorMsg.value = '无法访问麦克风: ' + e.message
      }
      onError && onError(errorMsg.value)
    }
  }

  function stopRecording() {
    _vadStopped = true
    _recordingStartedAt = 0
    if (_interimTimer) { clearInterval(_interimTimer); _interimTimer = null }
    if (_myvad) { _myvad.destroy(); _myvad = null }
    if (_audioCtx) { _audioCtx.close(); _audioCtx = null }
    if (_audioStream) { _audioStream.getTracks().forEach(t => t.stop()); _audioStream = null }
    _rawChunks.length = 0
    interimItem.zh = ''
    interimItem.en = ''
    isRecording.value = false
  }

  return { isRecording, errorMsg, interimItem, startRecording, stopRecording }
}
