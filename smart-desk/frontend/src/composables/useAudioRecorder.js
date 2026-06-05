import { ref, reactive } from 'vue'
import { api } from '../api/index.js'

const MAX_RECORDING_SEC = 20
const INTERIM_INTERVAL_MS = 800

/**
 * VAD-based audio recording + STT/translation upload.
 *
 * Interim: sends non-overlapping 2s new-audio chunks, backend accumulates text.
 *   No sliding window — never re-recognizes the same audio twice.
 * Final: sends VAD-segmented complete utterance with utterance_id.
 * Force-finalize: sends full accumulated audio, then resets VAD to stay in sync.
 */
export function useAudioRecorder({ meetingId, seatId, onSpeechStart, onInterim, onFinal, onError }) {
  const isRecording = ref(false)
  const errorMsg = ref('')
  const interimItem = reactive({ zh: '', en: '' })
  const _rawChunks = []
  let _vadStopped = false
  let _audioCtx = null
  let _audioStream = null
  let _workletNode = null
  let _silentGain = null
  let _interimTimer = null
  let _interimPending = false
  let _myvad = null
  let _recordingStartedAt = 0
  let _utteranceId = 0
  let _utteranceSeq = 0
  let _interimFailCount = 0
  let _lastInterimSampleIdx = 0

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
    const seq = _utteranceSeq  // capture at send time for barrier check
    const fullAudio = concatFloat32(_rawChunks)
    // Only new audio since last interim — non-overlapping, no re-recognition
    if (_lastInterimSampleIdx >= fullAudio.length) return
    const newAudio = fullAudio.slice(_lastInterimSampleIdx)
    if (newAudio.length < 16000) return // min 1s
    const sampleIdxBefore = fullAudio.length
    _interimPending = true
    try {
      const r = await api.uploadAudio(meetingId.value, seatId.value, float32ToWav(newAudio), false, _utteranceId)
      if (seq !== _utteranceSeq) return  // barrier: utterance ended while in flight
      if (r.ready === false || r.skipped) { /* models not ready or server busy */ }
      else if (r.zh) {
        interimItem.zh = r.zh
        interimItem.en = r.en || ''
        onInterim && onInterim(r.zh, r.en || '')
        _interimFailCount = 0  // reset on success
      }
      _lastInterimSampleIdx = sampleIdxBefore
    } catch {
      _interimFailCount++
      if (_interimFailCount >= 3 && onError) {
        onError('语音识别网络异常，请检查连接')
      }
    }
    finally { _interimPending = false }
  }

  async function finalizeUtterance(vadAudio) {
    _interimPending = false
    const wavBlob = float32ToWav(vadAudio)
    const maxRetries = 2
    let succeeded = false
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        const seq = _utteranceSeq  // capture for barrier check
        const r = await api.uploadAudio(meetingId.value, seatId.value, wavBlob, true, _utteranceId)
        if (_vadStopped || seq !== _utteranceSeq) return  // CR-009: stop barrier
        if (r.zh && r.zh !== '[无法识别语音]') {
          onFinal && onFinal(r.zh, r.en, r.seat_id || seatId.value, _utteranceId)
        }
        succeeded = true
        break
      } catch (e) {
        if (attempt < maxRetries) {
          await new Promise(r => setTimeout(r, 500 * (attempt + 1)))
          continue
        }
        errorMsg.value = '语音识别失败: ' + e.message
        onError && onError(e.message)
        // Fallback: use last interim text if final request fails
        if (interimItem.zh) {
          onFinal && onFinal(interimItem.zh, interimItem.en || '', seatId.value, _utteranceId)
        }
      }
    }
    interimItem.zh = ''
    interimItem.en = ''
    _rawChunks.length = 0
    _lastInterimSampleIdx = 0
    _recordingStartedAt = 0
  }

  function _resetVAD() {
    if (_myvad) {
      _myvad.destroy()
      _myvad = null
    }
  }

  function _stopAudioGraph() {
    if (_workletNode) { _workletNode.disconnect(); _workletNode = null }
    if (_silentGain) { _silentGain.disconnect(); _silentGain = null }
    if (_audioCtx) { _audioCtx.close(); _audioCtx = null }
    if (_audioStream) { _audioStream.getTracks().forEach(t => t.stop()); _audioStream = null }
  }

  async function _createVAD() {
    _myvad = await vad.MicVAD.new({
      onSpeechStart: () => {
        _utteranceId++
        _utteranceSeq++
        _lastInterimSampleIdx = 0
        interimItem.zh = ''
        interimItem.en = ''
        onSpeechStart && onSpeechStart()
      },
      onSpeechEnd: (audio) => {
        if (_vadStopped) return
        if (_interimTimer) { clearInterval(_interimTimer); _interimTimer = null }
        _utteranceSeq++  // invalidate in-flight interim responses
        finalizeUtterance(audio)
      },
      onVADMisfire: () => {},
      redemptionFrames: 30,
      preSpeechPadFrames: 20,
      minSpeechFrames: 16,
      positiveSpeechThreshold: 0.6,
      negativeSpeechThreshold: 0.4,
      onnxWASMBasePath: 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/',
      baseAssetPath: 'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/',
    })
    _myvad.start()
  }

  async function forceFinalize() {
    if (_vadStopped || !_rawChunks.length) return
    _interimPending = false
    _utteranceSeq++  // invalidate in-flight interim responses
    if (_interimTimer) { clearInterval(_interimTimer); _interimTimer = null }
    const fullAudio = concatFloat32(_rawChunks)
    if (fullAudio.length < 16000) return
    try {
      const seq = _utteranceSeq  // capture for barrier check
      const r = await api.uploadAudio(meetingId.value, seatId.value, float32ToWav(fullAudio), true, _utteranceId)
      if (_vadStopped || seq !== _utteranceSeq) return  // CR-009: stop barrier
      if (r.zh && r.zh !== '[无法识别语音]') {
        onFinal && onFinal(r.zh, r.en, r.seat_id || seatId.value, _utteranceId)
      }
    } catch (e) {
      errorMsg.value = '语音识别失败: ' + e.message
      onError && onError(e.message)
    }
    // Reset VAD state synchronously — critical: VAD state must match _rawChunks
    _rawChunks.length = 0
    _lastInterimSampleIdx = 0
    _recordingStartedAt = Date.now()
    interimItem.zh = ''
    interimItem.en = ''
    _resetVAD()
    await _createVAD()
    _interimTimer = setInterval(sendInterim, INTERIM_INTERVAL_MS)  // restart timer
  }

  async function startRecording() {
    try {
      _vadStopped = false
      _rawChunks.length = 0
      _interimPending = false
      _lastInterimSampleIdx = 0
      _recordingStartedAt = Date.now()
      interimItem.zh = ''
      interimItem.en = ''
      errorMsg.value = ''

      await _createVAD()

      _audioStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      _audioCtx = new AudioContext({ sampleRate: 16000 })
      await _audioCtx.audioWorklet.addModule('/audio-processor.js')
      const source = _audioCtx.createMediaStreamSource(_audioStream)
      _workletNode = new AudioWorkletNode(_audioCtx, 'audio-processor')
      _silentGain = _audioCtx.createGain()
      _silentGain.gain.value = 0
      _workletNode.port.onmessage = (e) => {
        if (_vadStopped) return
        _rawChunks.push(e.data) // Float32Array from worklet thread
        if (_recordingStartedAt && accumulatedDurationSec() >= MAX_RECORDING_SEC) {
          forceFinalize()
        }
      }
      source.connect(_workletNode)
      // Keep the worklet in the active audio graph without playing mic audio.
      _workletNode.connect(_silentGain)
      _silentGain.connect(_audioCtx.destination)

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

  async function stopRecording(options = {}) {
    const shouldFinalize = options.finalize === true
    const finalAudio = shouldFinalize && _rawChunks.length ? concatFloat32(_rawChunks) : null

    _utteranceSeq++  // Invalidate in-flight interim responses (CR-008)
    _recordingStartedAt = 0
    if (_interimTimer) { clearInterval(_interimTimer); _interimTimer = null }
    _resetVAD()
    _stopAudioGraph()
    isRecording.value = false

    if (finalAudio && finalAudio.length >= 16000) {
      _vadStopped = false
      await finalizeUtterance(finalAudio)
    } else {
      _rawChunks.length = 0
    }
    _vadStopped = true
    _lastInterimSampleIdx = 0
    interimItem.zh = ''
    interimItem.en = ''
  }

  return { isRecording, errorMsg, interimItem, startRecording, stopRecording, stop: stopRecording }
}
