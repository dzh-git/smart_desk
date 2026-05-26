<template>
  <div class="panel">
    <div class="section-head">
      <h3>多语言翻译</h3>
      <span class="lang-pair">中文 → English</span>
    </div>

    <!-- Voice input -->
    <div class="card voice-card" :class="{ listening: isListening }">
      <div class="voice-icon" @click="toggleListen">
        <div class="mic-circle" :class="{ active: isListening }">
          <span v-if="!isListening">🎤</span>
          <span v-else class="pulse-ring"></span>
        </div>
      </div>
      <div class="voice-text">
        <template v-if="isListening">正在聆听…</template>
        <template v-else-if="recognizedText">{{ recognizedText }}</template>
        <template v-else>点击麦克风开始说话</template>
      </div>
      <div class="voice-wave" v-if="isListening">
        <span v-for="i in 5" :key="i" class="wave-bar" :style="{ animationDelay: i * 0.1 + 's' }"></span>
      </div>
    </div>

    <!-- Manual input -->
    <div class="manual-section">
      <input v-model="inputText" placeholder="或直接输入中文…" @keyup.enter="doTranslate" />
      <button class="btn-primary btn-sm" @click="doTranslate" :disabled="!inputText.trim()">翻译</button>
    </div>

    <!-- Result -->
    <div v-if="result" class="card result-card">
      <div class="result-original">{{ result.original }}</div>
      <div class="result-arrow">↓</div>
      <div class="result-translated">{{ result.translated }}</div>
    </div>

    <!-- Error -->
    <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
  </div>
</template>

<script setup>
import { ref, onUnmounted } from 'vue'
import { api } from '../api/index.js'

const isListening = ref(false)
const recognizedText = ref('')
const inputText = ref('')
const result = ref(null)
const errorMsg = ref('')

let recognition = null

function initRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!SpeechRecognition) {
    errorMsg.value = '此浏览器不支持语音识别，请使用 Chrome'
    return
  }
  recognition = new SpeechRecognition()
  recognition.lang = 'zh-CN'
  recognition.interimResults = false
  recognition.continuous = false

  recognition.onresult = async (ev) => {
    const text = ev.results[0][0].transcript
    recognizedText.value = text
    isListening.value = false
    await doTranslateText(text)
  }

  recognition.onerror = () => {
    isListening.value = false
    errorMsg.value = '语音识别失败，请重试'
  }

  recognition.onend = () => {
    isListening.value = false
  }
}

function toggleListen() {
  if (!recognition) initRecognition()
  if (!recognition) return

  if (isListening.value) {
    recognition.stop()
    isListening.value = false
  } else {
    recognizedText.value = ''
    errorMsg.value = ''
    recognition.start()
    isListening.value = true
  }
}

async function doTranslate() {
  if (!inputText.value.trim()) return
  await doTranslateText(inputText.value.trim())
}

async function doTranslateText(text) {
  errorMsg.value = ''
  try {
    result.value = await api.translate({ text, source_lang: 'zh', target_lang: 'en' })
  } catch (e) {
    errorMsg.value = '翻译失败: ' + e.message
  }
}

onUnmounted(() => {
  if (recognition) recognition.stop()
})
</script>

<style scoped>
.lang-pair { font-size: var(--font-sm); color: var(--text-dim); }

.voice-card { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 32px; margin-bottom: 18px; transition: all 0.4s; }
.voice-card.listening { border-color: var(--accent); box-shadow: 0 0 28px var(--accent-glow); }

.mic-circle {
  width: 72px; height: 72px; border-radius: 50%;
  background: var(--bg-secondary);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; font-size: 28px;
  transition: all 0.3s;
  border: 2px solid transparent;
}
.mic-circle:hover { border-color: var(--accent); }
.mic-circle.active { border-color: var(--accent); animation: glow-breathe 1.5s infinite; }

.pulse-ring {
  width: 100%; height: 100%; border-radius: 50%;
  background: radial-gradient(circle, var(--accent) 0%, transparent 70%);
  opacity: 0.6;
}

.voice-text { font-size: var(--font-md); color: var(--text-secondary); min-height: 28px; }

.voice-wave { display: flex; gap: 4px; align-items: flex-end; height: 24px; }
.wave-bar { width: 4px; height: 12px; background: var(--accent); border-radius: 2px; animation: wave 0.6s infinite alternate; }
@keyframes wave { to { height: 24px; } }

.manual-section { display: flex; gap: 10px; margin-bottom: 18px; }
.manual-section input { flex: 1; }

.result-card { padding: 20px 24px; text-align: center; }
.result-original { font-size: var(--font-md); color: var(--text-secondary); margin-bottom: 8px; }
.result-arrow { font-size: 20px; color: var(--accent); margin-bottom: 8px; }
.result-translated { font-size: var(--font-lg); font-weight: 600; color: var(--text-primary); }

.error-msg { color: var(--danger); font-size: var(--font-sm); margin-top: 8px; }
</style>
