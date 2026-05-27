<template>
  <div class="panel">
    <div class="section-head">
      <h3>服务呼叫</h3>
      <button class="btn-ghost btn-sm" @click="$emit('close')" aria-label="关闭服务面板">✕</button>
    </div>

    <div class="service-grid">
      <button v-for="s in serviceTypes" :key="s.type" class="card service-btn" :aria-label="s.label" @click="doCall(s.type)">
        <span class="service-icon">{{ s.icon }}</span>
        <span class="service-label">{{ s.label }}</span>
      </button>
    </div>

    <div v-if="filteredCalls.length" class="call-history">
      <h4>{{ isAdmin ? '全部呼叫记录' : '我的呼叫记录' }}</h4>
      <div v-for="c in filteredCalls" :key="c.id" class="call-item">
        <span>{{ serviceIcon(c.service_type) }} {{ c.service_type }}</span>
        <span v-if="isAdmin" class="seat-badge">座位 {{ c.seat_id }}</span>
        <span class="badge" :class="statusClass(c.status)">{{ statusLabel(c.status) }}</span>
        <span class="call-time">{{ formatTime(c.created_at) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, inject } from 'vue'
import { api } from '../api/index.js'

const seatId = inject('seatId')
const isAdmin = inject('isAdmin')
const props = defineProps({ meetingId: Number, wsMsg: Object })

const calls = ref([])

const filteredCalls = computed(() => {
  if (isAdmin.value) return calls.value
  return calls.value.filter(c => c.seat_id === seatId.value)
})

const serviceTypes = [
  { type: 'coffee', icon: '☕', label: '咖啡' },
  { type: 'tea', icon: '🍵', label: '茶水' },
  { type: 'water', icon: '💧', label: '矿泉水' },
  { type: 'other', icon: '📋', label: '其他' },
]

onMounted(load)

async function load() {
  calls.value = await api.listServiceCalls(props.meetingId)
}

async function doCall(type) {
  await api.createServiceCall(props.meetingId, { seat_id: seatId.value, service_type: type })
  await load()
}

function serviceIcon(t) { return serviceTypes.find(s => s.type === t)?.icon || '📋' }

function statusClass(s) {
  return s === 'completed' ? 'badge-active' : s === 'acknowledged' ? 'badge-active' : 'badge-pending'
}
function statusLabel(s) {
  return s === 'completed' ? '已完成' : s === 'acknowledged' ? '已响应' : '待处理'
}
function formatTime(d) {
  return new Date(d).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

watch(() => props.wsMsg, (msg) => {
  if (msg?.type === 'service_update') load()
})
</script>

<style scoped>
.section-head { margin-bottom: 20px; }
.section-head h3 { font-size: var(--font-lg); }

.service-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }
.service-btn { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 28px 16px; cursor: pointer; }
.service-btn:active { transform: scale(0.95); }
.service-icon { font-size: 36px; }
.service-label { font-size: var(--font-md); color: var(--text-secondary); }

.call-history h4 { font-size: var(--font-md); margin-bottom: 10px; color: var(--text-secondary); }
.call-item { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: var(--font-sm); }
.seat-badge { font-size: var(--font-sm); color: var(--text-dim); }
.call-time { margin-left: auto; color: var(--text-dim); }
</style>
