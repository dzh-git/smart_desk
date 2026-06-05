<template>
  <div class="panel">
    <div class="section-head">
      <h3>发言席翻译</h3>
      <div class="head-actions">
        <button
          class="btn-ghost btn-sm"
          @click="openHistory"
          :class="{ 'has-dot': historyItems.length }"
        >历史</button>
        <button class="btn-ghost btn-sm" @click="$emit('close')" aria-label="关闭翻译面板">✕</button>
      </div>
    </div>

    <!-- Admin: designate speaker seat -->
    <div v-if="isAdmin" class="card admin-section">
      <label for="speaker-seat-select">指定发言席</label>
      <div class="speaker-row">
        <select id="speaker-seat-select" v-model.number="selectedSeat">
          <option v-for="s in 10" :key="s" :value="s">座位 {{ s }}</option>
        </select>
        <button class="btn-primary btn-sm" @click="setSpeaker">指定发言席</button>
      </div>
      <div v-if="speakingSeat" class="speaker-active">
        当前发言席：<strong>座位 {{ speakingSeat }}</strong>
        <button class="btn-ghost btn-sm" @click="clearSpeaker">取消</button>
      </div>
      <div v-else class="speaker-none">未指定发言席</div>
    </div>

    <!-- Non-speaker view -->
    <div v-if="!isAdmin && !isSpeaker && speakingSeat" class="card speaker-indicator">
      <span class="indicator-dot"></span>
      座位 {{ speakingSeat }} 正在发言…
    </div>

    <!-- Speaker: recording interface -->
    <div v-if="isSpeaker" class="card speaker-card" :class="{ recording: isRecording }">
      <button
        class="mic-btn"
        :class="{ active: isRecording }"
        @click="toggleRecord"
        :aria-label="isRecording ? '停止发言' : '开始发言'"
      >
        <span v-if="!isRecording" class="mic-icon">🎤</span>
        <span v-else class="mic-pulse"></span>
      </button>
      <div class="recording-hint">
        <template v-if="isRecording">正在聆听…</template>
        <template v-else>点击麦克风开始发言</template>
      </div>
      <div class="voice-wave" v-if="isRecording">
        <span v-for="i in 5" :key="i" class="wave-bar" :style="{ animationDelay: i * 0.1 + 's' }"></span>
      </div>
    </div>

    <!-- Model loading hint -->
    <div v-if="isSpeaker && !modelReady" class="card model-loading-hint">
      <span class="dot-flash"></span> 模型加载中，请稍候…
    </div>

    <!-- WS disconnect warning -->
    <div v-if="isSpeaker && wsConnected === false" class="card model-loading-hint" style="border-color: var(--danger);">
      <span class="dot-flash" style="background: var(--danger);"></span> 连接断开，正在重连…
    </div>

    <!-- No speaker seat yet -->
    <div v-if="!isAdmin && !speakingSeat" class="empty-sm">
      等待管理员指定发言席…
    </div>

    <!-- Two-line display: line1 = complete sentence, line2 = current -->
    <div v-if="line1.zh || line2.zh" class="transcript-current" :class="{ interim: !_isLine2Final }">
      <div v-if="line1.zh" class="transcript-line line-prev">
        <div class="transcript-zh">{{ line1.zh }}</div>
        <div class="transcript-en" v-if="line1.en">{{ line1.en }}</div>
      </div>
      <div class="transcript-line line-curr">
        <div class="transcript-zh">{{ line2.zh }}<span v-if="!_isLine2Final" class="cursor-blink">|</span></div>
        <div class="transcript-en" v-if="line2.en">{{ line2.en }}</div>
        <div class="transcript-en pending" v-else-if="line2.zh && !line2.en">
          <span class="dot-flash"></span> 翻译中…
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!line1.zh && !line2.zh" class="transcript-empty">
      发言内容将实时显示在这里
    </div>

    <!-- Error -->
    <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

    <!-- History modal -->
    <TranscriptHistoryModal
      :visible="showHistory"
      :items="historyItems"
      @close="showHistory = false"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch, inject } from 'vue'
import { api } from '../api/index.js'
import { useAudioRecorder } from '../composables/useAudioRecorder.js'
import TranscriptHistoryModal from './TranscriptHistoryModal.vue'

const seatId = inject('seatId')
const isAdmin = inject('isAdmin')
const props = defineProps({ meetingId: Number, wsMsg: Object, wsConnected: Boolean })
defineEmits(['close'])

const selectedSeat = ref(1)
const speakingSeat = ref(null)
const modelReady = ref(false)
const line1 = reactive({ zh: '', en: '' })
const line2 = reactive({ zh: '', en: '' })
let _isLine2Final = false
let _clearTranscriptTimer = null
const historyItems = reactive([])
const showHistory = ref(false)
let idCounter = 0
const _processedSegIds = new Set()
let _preloadPollTimer = null

function splitByPeriod(text) {
  if (!text) return []
  // Primary: sentence-final punctuation
  const parts = text.split(/(?<=[。！？.!?])/)
  const result = []
  for (const part of parts) {
    const s = part.trim()
    if (!s) continue
    // Fallback: long chunk with commas but no period → split on commas
    if (s.length > 15 && /[，,]/.test(s)) {
      const sub = s.split(/(?<=[，,])/)
      for (const ss of sub) {
        const t = ss.trim()
        if (t && t.length >= 6) result.push(t)
      }
    } else {
      result.push(s)
    }
  }
  // Length-based fallback: single chunk > 25 chars without any punctuation
  // → split by fixed length to keep display readable
  if (result.length === 1 && result[0].length > 25 && !/[。！？.!?，,]/.test(result[0])) {
    return chunkByLength(result[0], 25)
  }
  return result
}

function chunkByLength(text, charCount) {
  const result = []
  for (let i = 0; i < text.length; i += charCount) {
    result.push(text.slice(i, i + charCount))
  }
  return result
}

let _line1Zh = ''
let _line1En = ''
let _lastZh = ''   // guard against duplicate interim text from backend re-sends
let _transitionId = 0  // cancel stale transition animations

function animateTextTransition(fromZh, toZh, en, duration = 300) {
  if (!fromZh || fromZh === toZh) { updateLines(toZh, en, true); return }
  const tid = ++_transitionId
  const start = performance.now()
  const fromLen = fromZh.length; const toLen = toZh.length

  function step(now) {
    if (tid !== _transitionId) return  // cancelled by newer transition
    const progress = Math.min((now - start) / duration, 1)
    const eased = 1 - Math.pow(1 - progress, 3)  // ease-out cubic
    const splitPoint = Math.floor(toLen * eased)
    const displayZh = toZh.slice(0, splitPoint) + fromZh.slice(Math.min(splitPoint, fromLen))
    updateLines(displayZh, en, progress >= 1)
    if (progress < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
}

function clearTranscript() {
  ++_transitionId  // Cancel any in-flight text transition animation
  if (_clearTranscriptTimer) { clearTimeout(_clearTranscriptTimer); _clearTranscriptTimer = null }
  _line1Zh = ''; _line1En = ''; _lastZh = ''
  line1.zh = ''; line1.en = ''
  line2.zh = ''; line2.en = ''
  _isLine2Final = false
}

function updateLines(zh, en, isFinal) {
  if (!zh) return
  // Skip if identical to last display — prevents flicker & duplication
  if (zh === _lastZh && en === (line2.en || '') && !isFinal) return
  _lastZh = zh

  const zhSents = splitByPeriod(zh)
  const enSents = splitByPeriod(en)

  // line1: stable cache of second-to-last complete sentence
  // Only updates when a genuinely new second-to-last sentence appears
  if (zhSents.length >= 2) {
    const candidate = zhSents[zhSents.length - 2]
    if (candidate !== _line1Zh) {
      _line1Zh = candidate
      _line1En = enSents.length >= 2 ? enSents[Math.min(zhSents.length - 2, enSents.length - 1)] : (enSents[0] || '')
    }
    line1.zh = _line1Zh
    line1.en = _line1En
  } else {
    // Single sentence (no punctuation): clear line1 so old text doesn't
    // appear alongside the growing line2 — prevents visual duplication
    if (_line1Zh) { _line1Zh = ''; _line1En = ''; line1.zh = ''; line1.en = '' }
  }

  line2.zh = zhSents[zhSents.length - 1] || ''
  line2.en = enSents.length >= 1 ? enSents[enSents.length - 1] : (en || '')
  _isLine2Final = isFinal && /[。！？.!?，,]$/.test(line2.zh.trim())
}

function addHistory(zh, en, sid, segId) {
  // Audio-segment-based dedup: same segment → update, never duplicate
  if (segId != null) {
    let existing = null
    for (let i = historyItems.length - 1; i >= 0; i--) {
      if (historyItems[i].seg_id === segId) { existing = historyItems[i]; break }
    }
    if (existing) {
      existing.zh = zh
      existing.en = en
      existing.ts = Date.now() / 1000
      return
    }
  }
  historyItems.push({
    id: ++idCounter,
    zh, en,
    seat_id: sid || seatId.value,
    seg_id: segId,
    ts: Date.now() / 1000,
  })
  while (historyItems.length > 200) historyItems.shift()
}

const { isRecording, errorMsg, interimItem, startRecording, stopRecording } = useAudioRecorder({
  meetingId: computed(() => props.meetingId),
  seatId,
  onSpeechStart: () => { clearTranscript() },
  onInterim: (zh, en) => { updateLines(zh, en, false) },
  onFinal: (zh, en, sid, segId) => {
    if (segId != null) _processedSegIds.add(segId)
    // Smooth transition from streaming text to offline rescore result
    const currentZh = (line1.zh || '') + (line2.zh || '')
    if (currentZh && zh && zh !== currentZh) {
      animateTextTransition(currentZh, zh, en, 300)
    } else {
      updateLines(zh, en, true)
    }
    addHistory(zh, en, sid, segId)
    // Clear display after final — text lives in history, prevent stale overlap
    if (_clearTranscriptTimer) clearTimeout(_clearTranscriptTimer)
    _clearTranscriptTimer = setTimeout(clearTranscript, 5000)
  },
})

const isSpeaker = computed(() => speakingSeat.value && speakingSeat.value === seatId.value)

onMounted(async () => {
  try {
    const data = await api.getSpeakerSeat()
    speakingSeat.value = data.seat_id
  } catch (e) { console.error('Failed to get speaker seat:', e) }
  api.triggerPreload().catch(e => {
    errorMsg.value = `模型加载失败：${e.message || e}`
  })
  // Poll model ready status — non-blocking
  _preloadPollTimer = setInterval(async () => {
    try {
      const s = await api.getPreloadStatus()
      if (s.error) errorMsg.value = `模型加载失败：${s.error}`
      if (s.ready) {
        modelReady.value = true
        errorMsg.value = ''
        clearInterval(_preloadPollTimer)
        _preloadPollTimer = null
      }
    } catch (e) { console.error('Failed to get preload status:', e) }
  }, 2000)
})

// ── WS messages ──

watch(() => props.wsMsg, (msg) => {
  if (!msg) return
  if (msg.type === 'speaker_seat_set') {
    speakingSeat.value = msg.payload?.seat_id || null
    clearTranscript()
  }
  if (msg.type === 'speaker_seat_clear') {
    speakingSeat.value = null; stopRecording()
    clearTranscript()
  }
  if (msg.type === 'recording_stop' && msg.payload?.seat_id === seatId.value) {
    stopRecording()
    clearTranscript()
  }
  if (msg.type === 'translation_final') {
    const { zh, en, seat_id, segment_id, is_final } = msg.payload || {}
    if (zh === '[无法识别语音]' && en === '[translation unavailable]') return
    if (!zh && !en) return
    // Skip if already processed via HTTP response (speaker's own result)
    if (segment_id != null && _processedSegIds.has(segment_id)) return
    // Segment-id dedup: same segment_id → overwrite; is_final → freeze
    if (segment_id != null) {
      let existing = null
      for (let i = historyItems.length - 1; i >= 0; i--) {
        if (historyItems[i].seg_id === segment_id) { existing = historyItems[i]; break }
      }
      if (existing) {
        existing.zh = zh
        existing.en = en
        existing.ts = Date.now() / 1000
        if (is_final) existing._frozen = true
        updateLines(zh, en, is_final !== false)
        return
      }
    }
    updateLines(zh, en, is_final !== false)
    addHistory(zh, en, seat_id, segment_id)
  }
})

// ── Speaker seat ──

async function setSpeaker() {
  try {
    errorMsg.value = ''
    await api.setSpeakerSeat(selectedSeat.value, props.meetingId)
    speakingSeat.value = selectedSeat.value
  } catch (e) {
    errorMsg.value = `指定发言席失败：${e.message || e}`
    console.error('Failed to set speaker seat:', e)
  }
}

async function clearSpeaker() {
  try {
    errorMsg.value = ''
    await api.clearSpeakerSeat(props.meetingId)
    speakingSeat.value = null
  } catch (e) {
    errorMsg.value = `取消发言席失败：${e.message || e}`
    console.error('Failed to clear speaker seat:', e)
  }
}

// ── Recording toggle ──

async function toggleRecord() {
  if (isRecording.value) {
    await stopRecording({ finalize: true })
  } else {
    await startRecording()
  }
}

// ── History ──

async function openHistory() {
  showHistory.value = true
  try {
    const data = await api.getTranslationHistory(props.meetingId)
    if (data && data.length) mergeBackendHistory(data)
  } catch (e) { console.error('Failed to load translation history:', e) }
}

function mergeBackendHistory(backendEntries) {
  for (const e of backendEntries) {
    // Segment-id dedup: backend entry id is the segment_id
    if (e.id != null) {
      let existing = null
      for (let i = historyItems.length - 1; i >= 0; i--) {
        if (historyItems[i].seg_id === e.id) { existing = historyItems[i]; break }
      }
      if (existing) {
        existing.zh = e.zh
        existing.en = e.en
        existing.ts = e.ts
        continue
      }
    }
    historyItems.push({ id: ++idCounter, zh: e.zh, en: e.en, seat_id: e.seat_id, seg_id: e.id, ts: e.ts })
  }
  historyItems.sort((a, b) => (a.ts || 0) - (b.ts || 0))
  while (historyItems.length > 200) historyItems.shift()
  const latest = historyItems[historyItems.length - 1]
  if (latest && !line1.zh && !line2.zh) {
    updateLines(latest.zh, latest.en, true)
  }
}

onUnmounted(() => {
  stopRecording()
  if (_preloadPollTimer) clearInterval(_preloadPollTimer)
  if (_clearTranscriptTimer) clearTimeout(_clearTranscriptTimer)
})
</script>

<style scoped>
/* ── Head ── */
.head-actions { display: flex; align-items: center; gap: 6px; }
.head-actions .btn-ghost.has-dot { position: relative; color: var(--accent); }
.head-actions .btn-ghost.has-dot::after {
  content: ''; position: absolute; top: 4px; right: 4px;
  width: 7px; height: 7px; border-radius: 50%; background: var(--accent);
}

/* ── Admin section ── */
.admin-section { margin-bottom: 16px; }
.admin-section label { display: block; margin-bottom: 8px; font-size: var(--font-sm); color: var(--text-secondary); }
.speaker-row { display: flex; gap: 10px; }
.speaker-row select { width: auto; flex: 1; }
.speaker-active { margin-top: 12px; display: flex; align-items: center; gap: 8px; font-size: var(--font-sm); color: var(--accent); }
.speaker-none { margin-top: 8px; font-size: var(--font-sm); color: var(--text-dim); }

/* ── Speaker card ── */
.speaker-card {
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  padding: 24px; margin-bottom: 20px; transition: all 0.4s;
}
.speaker-card.recording { border-color: var(--accent); box-shadow: 0 0 28px var(--accent-glow); }
.mic-btn {
  width: 72px; height: 72px; border-radius: 50%;
  background: var(--bg-tertiary);
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; transition: all 0.3s;
  border: 2px solid var(--border-default);
}
.mic-btn:hover { border-color: var(--accent); transform: scale(1.05); }
.mic-btn.active { border-color: var(--accent); animation: glow-breathe 1.5s infinite; }
.mic-pulse {
  width: 55%; height: 55%; border-radius: 50%;
  background: radial-gradient(circle, var(--accent) 0%, transparent 70%); opacity: 0.6;
}
.recording-hint { font-size: var(--font-sm); color: var(--text-secondary); min-height: 22px; text-align: center; }
.voice-wave { display: flex; gap: 3px; align-items: flex-end; height: 20px; }
.wave-bar { width: 3px; height: 10px; background: var(--accent); border-radius: 2px; animation: wave 0.6s infinite alternate; }
@keyframes wave { to { height: 20px; } }

/* ── Non-speaker indicator ── */
.speaker-indicator {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 18px 24px; font-size: var(--font-md); color: var(--accent-light);
  margin-bottom: 20px; border: 1px solid rgba(91, 156, 230, 0.2);
}
.indicator-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); animation: pulse 1.2s ease-in-out infinite; }

/* ── Single current entry ── */
.transcript-current {
  padding: 16px 18px; margin-bottom: 10px;
  background: var(--bg-card); border-radius: var(--radius);
  border-left: 3px solid var(--accent); animation: fadeIn 0.25s var(--ease-out);
  min-height: 80px; max-height: 280px; overflow-y: auto;
}
.transcript-current.interim { border-left-color: var(--accent-light); background: rgba(91, 156, 230, 0.06); }
.transcript-empty { text-align: center; padding: 40px 0; color: var(--text-dim); font-size: var(--font-sm); }
.model-loading-hint { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 18px 24px; font-size: var(--font-sm); color: var(--text-secondary); margin-bottom: 20px; }

.transcript-zh { font-size: var(--font-md); color: var(--text-primary); line-height: 1.6; word-break: break-word; margin-bottom: 8px; }
.transcript-en { font-size: var(--font-sm); color: var(--accent-light); line-height: 1.5; word-break: break-word; padding-top: 8px; border-top: 1px solid var(--border-subtle); }
.transcript-en.pending { display: flex; align-items: center; gap: 8px; color: var(--text-dim); border-top-style: dashed; }
.transcript-en.interim-pulse { display: flex; align-items: center; gap: 8px; color: var(--text-dim); border-top: none; }

.dot-flash { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pulse 0.8s ease-in-out infinite; flex-shrink: 0; }
.cursor-blink { animation: blink 0.8s step-end infinite; color: var(--accent); }
@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }

.transcript-line.line-prev { opacity: 0.55; margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px dashed var(--border-subtle); }
.transcript-line.line-prev .transcript-zh { font-size: var(--font-sm); margin-bottom: 2px; }
.transcript-line.line-prev .transcript-en { font-size: var(--font-xs); padding-top: 2px; border-top: none; }

/* ── Error ── */
.error-msg { color: var(--danger); font-size: var(--font-sm); margin-top: 10px; text-align: center; }
</style>
