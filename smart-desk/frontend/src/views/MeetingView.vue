<template>
  <div class="meeting-view" v-if="meeting">
    <!-- Top bar -->
    <div class="top-row">
      <button class="btn-ghost btn-sm" @click="$router.push('/')">← 返回</button>
      <div class="meeting-title">
        <h1>{{ meeting.title }}</h1>
        <span class="badge" :class="statusClass(meeting.status)">{{ statusLabel(meeting.status) }}</span>
        <span class="ws-dot" :class="{ on: wsConnected }">{{ wsConnected ? '●' : '○' }}</span>
      </div>
      <div class="top-actions">
        <button class="btn-ghost btn-sm" @click="toggleStatus">
          {{ meeting.status === 'active' ? '结束' : '开始' }}
        </button>
        <span class="checkin-count">已签到 {{ checkedCount }}/8</span>
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

    <!-- Bottom action bar -->
    <div class="action-bar">
      <button class="action-btn" :class="{ active: showVoting }" @click="showVoting = !showVoting">
        <span class="action-icon">◈</span> 投票
      </button>
      <button class="action-btn" :class="{ active: showServices }" @click="showServices = !showServices">
        <span class="action-icon">☕</span> 服务
      </button>
      <button class="action-btn" :class="{ active: showAgendas }" @click="showAgendas = !showAgendas">
        <span class="action-icon">☰</span> 议程
      </button>
      <button class="action-btn" :class="{ active: showAttendees }" @click="showAttendees = !showAttendees">
        <span class="action-icon">👥</span> 参会者 {{ attendeeCount }}/8
      </button>
    </div>

    <!-- Overlay panels -->
    <transition name="slide-up">
      <div v-if="showVoting" class="overlay-panel">
        <VotingPanel :meeting-id="meetingId" :ws-msg="lastWsMsg" @close="showVoting = false" />
      </div>
    </transition>
    <transition name="slide-up">
      <div v-if="showServices" class="overlay-panel">
        <ServicePanel :meeting-id="meetingId" :ws-msg="lastWsMsg" @close="showServices = false" :seat-id="activeSeat" />
      </div>
    </transition>
    <transition name="slide-up">
      <div v-if="showAgendas" class="overlay-panel">
        <AgendaPanel :meeting-id="meetingId" @close="showAgendas = false" />
      </div>
    </transition>
    <transition name="slide-up">
      <div v-if="showAttendees" class="overlay-panel">
        <AttendeePanel :meeting-id="meetingId" :ws-msg="lastWsMsg" @close="showAttendees = false" />
      </div>
    </transition>
  </div>
  <div v-else class="loading">加载中…</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/index.js'
import { useWebSocket } from '../composables/useWebSocket.js'
import SeatGrid from '../components/SeatGrid.vue'
import VotingPanel from '../components/VotingPanel.vue'
import ServicePanel from '../components/ServicePanel.vue'
import AttendeePanel from '../components/AttendeePanel.vue'
import AgendaPanel from '../components/AgendaPanel.vue'
import { statusClass, statusLabel } from '../utils/status.js'

const route = useRoute()
const meetingId = Number(route.params.id)

const meeting = ref(null)
const lastWsMsg = ref(null)
const activeSeat = ref(1)
const showVoting = ref(false)
const showServices = ref(false)
const showAgendas = ref(false)
const showAttendees = ref(false)
const attendeeCount = ref(0)
const checkedCount = ref(0)

const { connected: wsConnected, connect, onMessage } = useWebSocket(meetingId)
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
})

function onSeatClick(seatId) {
  activeSeat.value = seatId
}

async function toggleStatus() {
  const newStatus = meeting.value.status === 'active' ? 'finished' : 'active'
  meeting.value = await api.updateMeeting(meetingId, { status: newStatus })
}
</script>

<style scoped>
.meeting-view {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px - 56px); /* minus topbar + padding */
}

.top-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
  flex-shrink: 0;
}
.meeting-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}
.meeting-title h1 {
  font-size: var(--font-xl);
  font-weight: 600;
}
.ws-dot { font-size: 12px; color: var(--text-dim); transition: color 0.3s; }
.ws-dot.on { color: var(--success); }
.top-actions { display: flex; align-items: center; gap: 12px; }
.checkin-count { font-size: var(--font-sm); color: var(--text-secondary); }

.grid-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
  padding: 10px 0;
}

.action-bar {
  display: flex;
  gap: 8px;
  justify-content: center;
  padding: 16px 0 0;
  flex-shrink: 0;
}
.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border: 1px solid rgba(255,255,255,0.06);
  padding: 10px 20px;
  border-radius: var(--radius);
  font-size: var(--font-sm);
  transition: all 0.25s;
}
.action-btn:hover { border-color: var(--text-dim); color: var(--text-primary); }
.action-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); box-shadow: 0 0 16px var(--accent-glow); }
.action-icon { font-size: 16px; }

.overlay-panel {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  max-height: 55vh;
  background: var(--bg-secondary);
  border-top: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  padding: 28px 32px;
  overflow-y: auto;
  z-index: 50;
  box-shadow: 0 -4px 30px rgba(0,0,0,0.5);
}

.loading {
  text-align: center;
  padding: 80px 0;
  color: var(--text-dim);
}
</style>
