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

    <!-- Model loading indicator -->
    <div v-if="!modelReady && showLoading" class="card model-loading">
      <span class="loading-spinner"></span>
      <span>模型加载中…</span>
    </div>

    <!-- Admin: designate speaker seat -->
    <div v-if="isAdmin" class="card admin-section">
      <label for="speaker-seat-select">指定发言席</label>
      <div class="speaker-row">
        <select id="speaker-seat-select" v-model.number="selectedSeat">
          <option v-for="s in 8" :key="s" :value="s">座位 {{ s }}</option>
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

    <!-- No speaker seat yet -->
    <div v-if="!isAdmin && !speakingSeat" class="empty-sm">
      等待管理员指定发言席…
    </div>

    <!-- Single current entry display -->
    <div v-if="currentEntry.zh" class="transcript-current">
      <div class="transcript-zh">{{ currentEntry.zh }}</div>
      <div class="transcript-en" v-if="currentEntry.en">{{ currentEntry.en }}</div>
      <div class="transcript-en pending" v-else>
        <span class="dot-flash"></span> 翻译中…
      </div>
    </div>

    <!-- Interim streaming -->
    <div v-if="interimItem.zh && !currentEntry.zh" class="transcript-current interim">
      <div class="transcript-zh">{{ interimItem.zh }}</div>
      <div class="transcript-en interim-pulse">
        <span class="dot-flash"></span>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!currentEntry.zh && !interimItem.zh" class="transcript-empty">
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
const currentEntry = reactive({ zh: '', en: '' })
const historyItems = reactive([])
const modelReady = ref(false)
const showLoading = ref(true)
const showHistory = ref(false)
let idCounter = 0
let _pollTimer = null
let _pollTimeout = null

function setEntry(zh, en, sid) {
  currentEntry.zh = zh
  currentEntry.en = en
  // Split long text into sentences for cleaner history entries
  const zhSents = splitSentences(zh)
  const enSents = splitSentences(en)
  const maxLen = Math.max(zhSents.length, enSents.length)
  const ts = Date.now() / 1000
  for (let i = 0; i < maxLen; i++) {
    historyItems.push({
      id: ++idCounter,
      zh: zhSents[i] || '',
      en: enSents[i] || '',
      seat_id: sid || seatId.value,
      ts,
    })
  }
  while (historyItems.length > 200) historyItems.shift()
}

function splitSentences(text) {
  if (!text) return ['']
  // Split by Chinese + English punctuation, keep delimiter with preceding text
  const parts = text.split(/(?<=[。！？，、；：\.!\?,;:])/g)
  return parts.filter(s => s.trim())
}

const { isRecording, errorMsg, interimItem, startRecording, stopRecording } = useAudioRecorder({
  meetingId: computed(() => props.meetingId),
  seatId,
  onFinal: (zh, en, sid) => setEntry(zh, en, sid),
})

const isSpeaker = computed(() => speakingSeat.value && speakingSeat.value === seatId.value)

onMounted(async () => {
  try {
    const data = await api.getSpeakerSeat(props.meetingId)
    speakingSeat.value = data.speaker_seat
  } catch {}
  checkModelStatus()
})

async function checkModelStatus() {
  try {
    const status = await api.getPreloadStatus()
    if (status.ready) { modelReady.value = true; showLoading.value = false; return }
    api.preloadModels().catch(() => {})
    _pollTimer = setInterval(async () => {
      try {
        const s = await api.getPreloadStatus()
        if (s.ready) { modelReady.value = true; showLoading.value = false; stopPolling() }
      } catch { stopPolling() }
    }, 2000)
    _pollTimeout = setTimeout(() => { showLoading.value = false; stopPolling() }, 30000)
  } catch { showLoading.value = false }
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null }
  if (_pollTimeout) { clearTimeout(_pollTimeout); _pollTimeout = null }
}

// ── WS messages ──

watch(() => props.wsMsg, (msg) => {
  if (!msg) return
  if (msg.type === 'speaker_seat_set') speakingSeat.value = msg.payload?.seat_id || null
  if (msg.type === 'speaker_seat_clear') { speakingSeat.value = null; stopRecording() }
  if (msg.type === 'translation_result') {
    const { zh, en, seat_id } = msg.payload
    if (zh === '[无法识别语音]' && en === '[translation unavailable]') return
    if (!zh && !en) return
    if (currentEntry.zh === zh && currentEntry.en === en) return
    setEntry(zh, en, seat_id)
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
  const seen = new Set(historyItems.map((it) => `${it.zh}|${it.seat_id}|${it.ts}`))
  for (const e of backendEntries) {
    const key = `${e.zh}|${e.seat_id}|${e.ts}`
    if (seen.has(key)) continue
    seen.add(key)
    historyItems.push({ id: ++idCounter, zh: e.zh, en: e.en, seat_id: e.seat_id, ts: e.ts })
  }
  historyItems.sort((a, b) => (a.ts || 0) - (b.ts || 0))
  while (historyItems.length > 200) historyItems.shift()
  const latest = historyItems[historyItems.length - 1]
  if (latest && !currentEntry.zh) {
    currentEntry.zh = latest.zh
    currentEntry.en = latest.en
  }
}

onUnmounted(() => {
  stopRecording()
  stopPolling()
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

/* ── Model loading ── */
.model-loading {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 16px 24px; margin-bottom: 16px; font-size: var(--font-sm);
  color: var(--accent-light); border: 1px solid rgba(91, 156, 230, 0.2);
}
.loading-spinner {
  width: 16px; height: 16px;
  border: 2px solid var(--border-default); border-top-color: var(--accent);
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

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
  min-height: 80px;
}
.transcript-current.interim { border-left-color: var(--accent-light); background: rgba(91, 156, 230, 0.06); }
.transcript-empty { text-align: center; padding: 40px 0; color: var(--text-dim); font-size: var(--font-sm); }

.transcript-zh { font-size: var(--font-md); color: var(--text-primary); line-height: 1.6; word-break: break-word; margin-bottom: 8px; }
.transcript-en { font-size: var(--font-sm); color: var(--accent-light); line-height: 1.5; word-break: break-word; padding-top: 8px; border-top: 1px solid var(--border-subtle); }
.transcript-en.pending { display: flex; align-items: center; gap: 8px; color: var(--text-dim); border-top-style: dashed; }
.transcript-en.interim-pulse { display: flex; align-items: center; gap: 8px; color: var(--text-dim); border-top: none; }

.dot-flash { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pulse 0.8s ease-in-out infinite; flex-shrink: 0; }

/* ── Error ── */
.error-msg { color: var(--danger); font-size: var(--font-sm); margin-top: 10px; text-align: center; }
</style>
