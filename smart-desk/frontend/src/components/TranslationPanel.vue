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
const props = defineProps({ meetingId: Number, wsMsg: Object })
defineEmits(['close'])

const selectedSeat = ref(1)
const speakingSeat = ref(null)
const modelReady = ref(false)
const line1 = reactive({ zh: '', en: '' })
const line2 = reactive({ zh: '', en: '' })
let _isLine2Final = false
const historyItems = reactive([])
const showHistory = ref(false)
let idCounter = 0
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
    // SenseVoice may output ， instead of 。 between sentences in continuous speech
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
  return result
}

function textSimilar(a, b) {
  if (!a || !b) return 0
  const shorter = a.length < b.length ? a : b
  const longer = a.length < b.length ? b : a
  if (shorter.length === 0) return 0
  let matches = 0
  for (let i = 0; i < shorter.length; i++) {
    if (shorter[i] === longer[i]) matches++
  }
  return matches / longer.length
}

let _line1Zh = ''
let _line1En = ''

function updateLines(zh, en, isFinal) {
  if (!zh) return
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
  }
  // When < 2 sentences, keep line1 as-is (stable, doesn't disappear)

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
  onSpeechStart: () => { _line1Zh = ''; _line1En = ''; line1.zh = ''; line1.en = ''; line2.zh = ''; line2.en = ''; _isLine2Final = false },
  onInterim: (zh, en) => { updateLines(zh, en, false) },
  onFinal: (zh, en, sid, segId) => { updateLines(zh, en, true); addHistory(zh, en, sid, segId) },
})

const isSpeaker = computed(() => speakingSeat.value && speakingSeat.value === seatId.value)

onMounted(async () => {
  try {
    const data = await api.getSpeakerSeat(props.meetingId)
    speakingSeat.value = data.speaker_seat
  } catch {}
  // Poll model ready status — non-blocking
  _preloadPollTimer = setInterval(async () => {
    try {
      const s = await api.getPreloadStatus()
      if (s.ready) {
        modelReady.value = true
        clearInterval(_preloadPollTimer)
        _preloadPollTimer = null
      }
    } catch {}
  }, 2000)
})

// ── WS messages ──

watch(() => props.wsMsg, (msg) => {
  if (!msg) return
  if (msg.type === 'speaker_seat_set') {
    speakingSeat.value = msg.payload?.seat_id || null
    _line1Zh = ''; _line1En = ''; line1.zh = ''; line1.en = ''; line2.zh = ''; line2.en = ''; _isLine2Final = false
  }
  if (msg.type === 'speaker_seat_clear') {
    speakingSeat.value = null; stopRecording()
    _line1Zh = ''; _line1En = ''; line1.zh = ''; line1.en = ''; line2.zh = ''; line2.en = ''; _isLine2Final = false
  }
  if (msg.type === 'translation_result') {
    const { zh, en, seat_id } = msg.payload
    if (zh === '[无法识别语音]' && en === '[translation unavailable]') return
    if (!zh && !en) return
    // WS echo: dedup by timestamp proximity + text similarity
    const last = historyItems[historyItems.length - 1]
    if (last && (Date.now() / 1000 - last.ts) < 8 && textSimilar(last.zh, zh) > 0.8) return
    updateLines(zh, en, true)
    addHistory(zh, en, seat_id, undefined)
  }
})

// ── Speaker seat ──

async function setSpeaker() {
  await api.setSpeakerSeat(props.meetingId, selectedSeat.value)
  speakingSeat.value = selectedSeat.value
}

async function clearSpeaker() {
  await api.setSpeakerSeat(props.meetingId, 0)
  speakingSeat.value = null
}

// ── Recording toggle ──

function toggleRecord() {
  isRecording.value ? stopRecording() : startRecording()
}

// ── History ──

async function openHistory() {
  showHistory.value = true
  try {
    const data = await api.getTranscriptHistory(props.meetingId)
    if (data.entries && data.entries.length) mergeBackendHistory(data.entries)
  } catch { /* local fine */ }
}

function mergeBackendHistory(backendEntries) {
  for (const e of backendEntries) {
    // Check time proximity (<8s) + text similarity for dedup
    const last = historyItems[historyItems.length - 1]
    if (last && Math.abs((last.ts || 0) - (e.ts || 0)) < 8 && textSimilar(last.zh, e.zh) > 0.8) continue
    historyItems.push({ id: ++idCounter, zh: e.zh, en: e.en, seat_id: e.seat_id, ts: e.ts })
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
