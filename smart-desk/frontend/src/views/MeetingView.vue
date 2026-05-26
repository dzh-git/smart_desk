<template>
  <div class="meeting-detail" v-if="meeting">
    <!-- Header -->
    <div class="detail-header">
      <button class="btn-ghost btn-sm" @click="$router.push('/')">← 返回</button>
      <div class="header-info">
        <h1>{{ meeting.title }}</h1>
        <span class="badge" :class="statusClass(meeting.status)">{{ statusLabel(meeting.status) }}</span>
      </div>
      <div class="header-actions">
        <button
          class="btn-ghost btn-sm"
          @click="toggleStatus"
        >
          {{ meeting.status === 'active' ? '结束会议' : '开始会议' }}
        </button>
      </div>
    </div>

    <!-- WS indicator -->
    <div class="ws-indicator" :class="{ connected: wsConnected }">
      {{ wsConnected ? '● 实时连接' : '○ 连接中…' }}
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button v-for="t in tabs" :key="t.key" class="tab-btn" :class="{ active: activeTab === t.key }" @click="activeTab = t.key">
        {{ t.label }}
      </button>
    </div>

    <!-- Tab content -->
    <transition name="fade" mode="out-in">
      <AttendeePanel v-if="activeTab === 'attendees'" :meeting-id="meeting.id" :ws-msg="lastWsMsg" key="a" />
      <VotingPanel v-else-if="activeTab === 'voting'" :meeting-id="meeting.id" :ws-msg="lastWsMsg" key="v" />
      <TranslationPanel v-else-if="activeTab === 'translation'" key="t" />
      <ServicePanel v-else-if="activeTab === 'services'" :meeting-id="meeting.id" :ws-msg="lastWsMsg" key="s" />
      <div v-else key="agenda" class="agenda-tab">
        <div class="section-head">
          <h3>会议议程</h3>
          <button class="btn-primary btn-sm" @click="showAddAgenda = true">+ 添加</button>
        </div>
        <div v-if="!agendas.length" class="empty-sm">暂无议程</div>
        <div v-else class="agenda-list">
          <div v-for="a in agendas" :key="a.id" class="agenda-item card">
            <span>{{ a.title }}</span>
            <button class="btn-ghost btn-sm" @click="removeAgenda(a.id)">删除</button>
          </div>
        </div>
        <div v-if="showAddAgenda" class="inline-form">
          <input v-model="newAgendaTitle" placeholder="议程内容" @keyup.enter="addAgenda" />
          <button class="btn-primary btn-sm" @click="addAgenda">确认</button>
          <button class="btn-ghost btn-sm" @click="showAddAgenda = false">取消</button>
        </div>
      </div>
    </transition>
  </div>
  <div v-else class="loading">加载中…</div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/index.js'
import { useWebSocket } from '../composables/useWebSocket.js'
import AttendeePanel from '../components/AttendeePanel.vue'
import VotingPanel from '../components/VotingPanel.vue'
import TranslationPanel from '../components/TranslationPanel.vue'
import ServicePanel from '../components/ServicePanel.vue'
import { statusClass, statusLabel } from '../utils/status.js'

const route = useRoute()
const meetingId = Number(route.params.id)

const meeting = ref(null)
const agendas = ref([])
const activeTab = ref('agenda')
const showAddAgenda = ref(false)
const newAgendaTitle = ref('')
const lastWsMsg = ref(null)

const tabs = [
  { key: 'agenda', label: '议程' },
  { key: 'attendees', label: '参会者' },
  { key: 'voting', label: '投票' },
  { key: 'translation', label: '翻译' },
  { key: 'services', label: '服务' },
]

// WebSocket
const { connected: wsConnected, connect, onMessage } = useWebSocket(meetingId)
onMessage((msg) => { lastWsMsg.value = msg })
connect()

// Load
async function load() {
  const [m, a] = await Promise.all([
    api.getMeeting(meetingId),
    api.listAgendas(meetingId),
  ])
  meeting.value = m
  agendas.value = a
}
onMounted(load)

async function toggleStatus() {
  const newStatus = meeting.value.status === 'active' ? 'finished' : 'active'
  meeting.value = await api.updateMeeting(meetingId, { status: newStatus })
}

async function addAgenda() {
  if (!newAgendaTitle.value.trim()) return
  const a = await api.addAgenda(meetingId, { title: newAgendaTitle.value, sort_order: agendas.value.length })
  agendas.value.push(a)
  newAgendaTitle.value = ''
  showAddAgenda.value = false
}

async function removeAgenda(id) {
  await api.removeAgenda(meetingId, id)
  agendas.value = agendas.value.filter(a => a.id !== id)
}

</script>

<style scoped>
.meeting-detail { max-width: 1100px; margin: 0 auto; }

.detail-header { display: flex; align-items: center; gap: 16px; margin-bottom: 8px; }
.header-info { display: flex; align-items: center; gap: 12px; flex: 1; }
.header-info h1 { font-size: var(--font-xl); font-weight: 600; }

.ws-indicator { font-size: var(--font-sm); color: var(--text-dim); margin-bottom: 12px; transition: color 0.3s; }
.ws-indicator.connected { color: var(--success); }

.tabs { display: flex; gap: 6px; margin-bottom: 24px; }
.tab-btn {
  background: transparent;
  color: var(--text-secondary);
  padding: 8px 20px;
  border-radius: 20px;
  font-size: var(--font-sm);
  border: 1px solid transparent;
  transition: all 0.25s;
}
.tab-btn:hover { color: var(--text-primary); border-color: var(--text-dim); }
.tab-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }

.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.section-head h3 { font-size: var(--font-lg); }

.agenda-item { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding: 14px 20px; }

.inline-form { display: flex; gap: 8px; margin-top: 12px; }
.inline-form input { flex: 1; }

.empty-sm { text-align: center; padding: 40px 0; color: var(--text-dim); }
.loading { text-align: center; padding: 80px 0; color: var(--text-dim); }
</style>
