<template>
  <div class="meeting-view" v-if="meeting" @keydown.escape="closeAll">
    <!-- Top row -->
    <div class="top-row">
      <button class="btn-ghost btn-sm back-btn" @click="$router.push('/')" aria-label="返回会议列表">
        <span class="back-arrow">←</span>
        <span>返回</span>
      </button>
      <div class="meeting-title">
        <h1>{{ meeting.title }}</h1>
        <span class="badge" :class="statusClass(meeting.status)">{{ statusLabel(meeting.status) }}</span>
        <span class="ws-dot" :class="{ on: wsConnected }" :title="wsConnected ? '已连接' : '未连接'"></span>
      </div>
      <div class="top-actions">
        <button
          v-if="isAdmin"
          class="btn-primary btn-sm"
          @click="toggleStatus"
        >
          {{ meeting.status === 'active' ? '结束会议' : '开始会议' }}
        </button>
        <span class="checkin-count">
          <span class="checkin-icon">✓</span>
          已签到 {{ checkedCount }}/8
        </span>
      </div>
    </div>

    <!-- 8-seat grid -->
    <div class="grid-area">
      <SeatGrid
        :meeting-id="meetingId"
        :ws-msg="lastWsMsg"
        @seat-click="onSeatClick"
      />
    </div>

    <!-- Bottom action bar - pill container -->
    <div class="action-bar-wrap">
      <nav class="action-bar glass" aria-label="功能面板">
        <button
          class="action-btn"
          :class="{ active: showVoting }"
          @click="togglePanel('voting')"
          aria-label="投票"
        >
          <span class="action-icon">◈</span>
          <span class="action-label">投票</span>
        </button>
        <button
          class="action-btn"
          :class="{ active: showServices }"
          @click="togglePanel('services')"
          aria-label="服务呼叫"
        >
          <span class="action-icon">☕</span>
          <span class="action-label">服务</span>
        </button>
        <button
          class="action-btn"
          :class="{ active: showAgendas }"
          @click="togglePanel('agendas')"
          aria-label="议程"
        >
          <span class="action-icon">☰</span>
          <span class="action-label">议程</span>
        </button>
        <button
          class="action-btn"
          :class="{ active: showAttendees }"
          @click="togglePanel('attendees')"
          aria-label="参会者"
        >
          <span class="action-icon">👥</span>
          <span class="action-label">参会者</span>
          <span class="count-badge">{{ attendeeCount }}/8</span>
        </button>
        <button
          class="action-btn"
          :class="{ active: showTranslation }"
          @click="togglePanel('translation')"
          aria-label="翻译"
        >
          <span class="action-icon">🌐</span>
          <span class="action-label">翻译</span>
        </button>
      </nav>
    </div>

    <!-- Overlay backdrop -->
    <transition name="overlay-fade">
      <div v-if="anyOpen" class="panel-backdrop" @click="closeAll"></div>
    </transition>

    <!-- Overlay panels -->
    <transition name="slide-up">
      <div v-if="showVoting" class="overlay-panel glass">
        <VotingPanel :meeting-id="meetingId" :ws-msg="lastWsMsg" @close="showVoting = false" />
      </div>
    </transition>
    <transition name="slide-up">
      <div v-if="showServices" class="overlay-panel glass">
        <ServicePanel :meeting-id="meetingId" :ws-msg="lastWsMsg" @close="showServices = false" :seat-id="activeSeat" />
      </div>
    </transition>
    <transition name="slide-up">
      <div v-if="showAgendas" class="overlay-panel glass">
        <AgendaPanel :meeting-id="meetingId" @close="showAgendas = false" />
      </div>
    </transition>
    <transition name="slide-up">
      <div v-if="showAttendees" class="overlay-panel glass">
        <AttendeePanel :meeting-id="meetingId" :ws-msg="lastWsMsg" @close="showAttendees = false" />
      </div>
    </transition>
    <transition name="slide-up">
      <div v-if="showTranslation" class="overlay-panel glass">
        <TranslationPanel :meeting-id="meetingId" :ws-msg="lastWsMsg" @close="showTranslation = false" />
      </div>
    </transition>
  </div>
  <div v-else class="loading-state">
    <div class="skeleton" style="width:240px;height:28px;margin:0 auto 20px;"></div>
    <div class="skeleton" style="width:100%;height:320px;max-width:900px;margin:0 auto;"></div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/index.js'
import { useSeat } from '../composables/useSeat.js'
import { useWebSocket } from '../composables/useWebSocket.js'
import SeatGrid from '../components/SeatGrid.vue'
import VotingPanel from '../components/VotingPanel.vue'
import ServicePanel from '../components/ServicePanel.vue'
import AttendeePanel from '../components/AttendeePanel.vue'
import TranslationPanel from '../components/TranslationPanel.vue'
import AgendaPanel from '../components/AgendaPanel.vue'
import { statusClass, statusLabel } from '../utils/status.js'

const route = useRoute()
const { seatId, isAdmin } = useSeat()
const meetingId = Number(route.params.id)

const meeting = ref(null)
const lastWsMsg = ref(null)
const activeSeat = ref(1)
const showVoting = ref(false)
const showServices = ref(false)
const showAgendas = ref(false)
const showAttendees = ref(false)
const showTranslation = ref(false)
const attendeeCount = ref(0)
const checkedCount = ref(0)

const anyOpen = computed(() => showVoting.value || showServices.value || showAgendas.value || showAttendees.value || showTranslation.value)

const { connected: wsConnected, connect, onMessage } = useWebSocket(meetingId, seatId.value)
onMessage((msg) => { lastWsMsg.value = msg })
connect()

async function load() {
  meeting.value = await api.getMeeting(meetingId)
  attendeeCount.value = meeting.value.attendee_count
  checkedCount.value = meeting.value.checked_in_count
}
onMounted(load)

watch(lastWsMsg, (msg) => {
  if (msg?.type === 'check_in') checkedCount.value++
  if (msg?.type === 'meeting_ended') meeting.value.status = 'finished'
  if (msg?.type === 'meeting_started') {
    meeting.value.status = 'active'
    api.preloadModels().catch(() => {})
  }
})

function onSeatClick(seatId) {
  activeSeat.value = seatId
}

async function toggleStatus() {
  const newStatus = meeting.value.status === 'active' ? 'finished' : 'active'
  meeting.value = await api.updateMeeting(meetingId, { status: newStatus })
  if (newStatus === 'active') {
    api.preloadModels().catch(() => {})
  }
}

function togglePanel(name) {
  const map = { voting: showVoting, services: showServices, agendas: showAgendas, attendees: showAttendees, translation: showTranslation }
  const ref = map[name]
  ref.value = !ref.value
}

function closeAll() {
  showVoting.value = false
  showServices.value = false
  showAgendas.value = false
  showAttendees.value = false
  showTranslation.value = false
}
</script>

<style scoped>
.meeting-view {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px - 56px);
  outline: none;
}

/* Top row */
.top-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
  flex-shrink: 0;
}
.back-btn { gap: 6px; }
.back-arrow { font-size: 16px; }
.meeting-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}
.meeting-title h1 {
  font-size: var(--font-xl);
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ws-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--text-dim);
  flex-shrink: 0;
  transition: all 0.3s var(--ease-out);
}
.ws-dot.on { background: var(--success); box-shadow: 0 0 8px var(--success-glow); }
.top-actions { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.checkin-count {
  font-size: var(--font-sm);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
}
.checkin-icon { color: var(--success); font-weight: 700; }

/* Grid area */
.grid-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
  padding: 10px 0;
}

/* Action bar */
.action-bar-wrap {
  flex-shrink: 0;
  padding: 20px 0 4px;
  display: flex;
  justify-content: center;
}
.action-bar {
  display: inline-flex;
  gap: 4px;
  padding: 6px;
  border-radius: var(--radius-xl);
}
.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  color: var(--text-secondary);
  padding: 10px 18px;
  border-radius: var(--radius-lg);
  font-size: var(--font-sm);
  font-weight: 500;
  transition: all var(--duration-fast) var(--ease-out);
  position: relative;
}
.action-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
}
.action-btn.active {
  background: var(--accent);
  color: #fff;
  box-shadow: 0 4px 16px var(--accent-glow);
}
.action-icon { font-size: 16px; }
.action-label { display: none; }
.count-badge {
  font-size: var(--font-xs);
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: rgba(255, 255, 255, 0.15);
  color: var(--text-primary);
}
.action-btn.active .count-badge { background: rgba(255, 255, 255, 0.25); }

@media (min-width: 640px) {
  .action-label { display: inline; }
}

/* Backdrop */
.panel-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 45;
}
.overlay-fade-enter-active { transition: opacity 0.3s var(--ease-out); }
.overlay-fade-leave-active { transition: opacity 0.25s var(--ease-out); }
.overlay-fade-enter-from,
.overlay-fade-leave-to { opacity: 0; }

/* Overlay panels */
.overlay-panel {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  max-height: 55vh;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-xl) var(--radius-xl) 0 0;
  padding: 32px 36px;
  overflow-y: auto;
  z-index: 50;
  box-shadow: 0 -8px 40px rgba(0, 0, 0, 0.5);
}

/* Loading */
.loading-state {
  max-width: 1100px;
  margin: 0 auto;
  padding-top: 40px;
}
</style>
