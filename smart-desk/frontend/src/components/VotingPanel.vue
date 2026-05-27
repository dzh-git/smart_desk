<template>
  <div class="panel">
    <div class="section-head">
      <h3>投票表决</h3>
      <div style="display:flex;gap:8px">
        <button v-if="isAdmin" class="btn-gold btn-sm" @click="showCreate = true">+ 发起投票</button>
        <button class="btn-ghost btn-sm" @click="$emit('close')" aria-label="关闭投票面板">✕</button>
      </div>
    </div>

    <div v-if="!votes.length" class="empty-sm">暂无投票</div>

    <div v-for="(v, vi) in votes" :key="v.id" class="card vote-card">
      <div class="vote-header">
        <h4>{{ v.title }}</h4>
        <span class="badge" :class="v.status === 'open' ? 'badge-active' : 'badge-done'">
          {{ v.status === 'open' ? '投票中' : '已关闭' }}
        </span>
      </div>

      <!-- ECharts ring chart -->
      <div class="chart-wrap">
        <div :ref="el => chartRefs[v.id] = el" class="chart-box"></div>
        <div class="chart-total" v-if="totalVotes(v) > 0">
          <span class="total-num">{{ totalVotes(v) }}</span>
          <span class="total-label">总票数</span>
        </div>
      </div>

      <!-- Cast vote -->
      <div v-if="v.status === 'open'" class="cast-section">
        <div class="cast-options">
          <button
            v-for="opt in v.options" :key="opt"
            class="btn-ghost btn-sm cast-btn"
            :class="{ selected: selected[v.id] === opt }"
            @click="selected[v.id] = opt"
          >{{ opt }}</button>
        </div>
        <button class="btn-primary btn-sm" @click="doCast(v)" :disabled="!selected[v.id]">确认投票</button>
      </div>

      <button v-if="v.status === 'open' && isAdmin" class="btn-ghost btn-sm close-btn" @click="doClose(v)">关闭投票</button>
    </div>

    <!-- Create dialog -->
    <BaseDialog v-model="showCreate" title="发起投票">
      <label>投票主题</label>
      <input v-model="voteForm.title" placeholder="如：请对提案一进行表决" />
      <label>选项（每行一个）</label>
      <textarea v-model="voteForm.optionsText" rows="4" placeholder="同意&#10;反对&#10;弃权"></textarea>
      <template #actions>
        <button class="btn-ghost" @click="showCreate = false">取消</button>
        <button class="btn-gold" @click="doCreate" :disabled="!voteForm.title.trim()">发起投票</button>
      </template>
    </BaseDialog>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick, inject } from 'vue'
import * as echarts from 'echarts'
import { api } from '../api/index.js'
import BaseDialog from './shared/BaseDialog.vue'

const seatId = inject('seatId')
const isAdmin = inject('isAdmin')
const props = defineProps({ meetingId: Number, wsMsg: Object })

const votes = ref([])
const selected = ref({})
const showCreate = ref(false)
const voteForm = ref({ title: '', optionsText: '同意\n反对\n弃权' })
const chartRefs = ref({})
const charts = {}

onMounted(load)

async function load() {
  votes.value = await api.listVotes(props.meetingId)
  await nextTick()
  votes.value.forEach(v => renderChart(v))
}

function totalVotes(v) {
  return v.results?.reduce((s, r) => s + r.count, 0) || 0
}

function renderChart(v) {
  const el = chartRefs.value[v.id]
  if (!el) return

  if (charts[v.id]) charts[v.id].dispose()

  const names = v.results?.map(r => r.option) || v.options
  const data = v.results?.map(r => ({ name: r.option, value: r.count }))
    || v.options.map(o => ({ name: o, value: 0 }))

  const total = totalVotes(v)

  const chart = echarts.init(el, null, { devicePixelRatio: 2 })
  chart.setOption({
    color: ['#4a90d9', '#c9a84c', '#3cb878', '#e05555', '#8b5cf6', '#f59e0b'],
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1a1a2e',
      borderColor: '#2a2a40',
      textStyle: { color: '#e8e8f0', fontSize: 13 },
      formatter: '{b}: {c} 票 ({d}%)',
    },
    series: [{
      type: 'pie',
      radius: ['55%', '78%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      itemStyle: {
        borderRadius: 6,
        borderColor: '#12121a',
        borderWidth: 4,
      },
      label: {
        show: true,
        position: 'outside',
        color: '#8888a0',
        fontSize: 13,
        formatter: '{b}\n{d}%',
      },
      labelLine: {
        lineStyle: { color: '#444' },
      },
      emphasis: {
        label: { fontSize: 16, fontWeight: 'bold' },
        scaleSize: 12,
      },
      animationType: 'scale',
      animationEasing: 'elasticOut',
      animationDuration: 800,
      data,
    }],
  })

  if (total === 0) {
    // show placeholder when no votes
    chart.setOption({
      graphic: [{
        type: 'text',
        left: 'center',
        top: 'center',
        style: { text: '等待投票…', fill: '#555570', fontSize: 14 },
      }],
    })
  }

  charts[v.id] = chart
}

async function doCreate() {
  const options = voteForm.value.optionsText.split('\n').map(s => s.trim()).filter(Boolean)
  if (!options.length) return
  await api.createVote(props.meetingId, { title: voteForm.value.title, options })
  showCreate.value = false
  voteForm.value = { title: '', optionsText: '同意\n反对\n弃权' }
  await load()
}

async function doCast(v) {
  const opt = selected.value[v.id]
  if (!opt) return
  // Look up attendee_id by seat_id (they're different)
  let attendeeId = seatId.value
  try {
    const attendees = await api.listAttendees(props.meetingId)
    const att = attendees.find(a => a.seat_id === seatId.value)
    if (att) attendeeId = att.id
  } catch {}
  await api.castVote(props.meetingId, v.id, { attendee_id: attendeeId, option: opt })
  selected.value[v.id] = null
  await load()
}

async function doClose(v) {
  await api.closeVote(props.meetingId, v.id)
  await load()
}

watch(() => props.wsMsg, (msg) => {
  if (msg?.type === 'vote_update') load()
})

onUnmounted(() => {
  Object.values(charts).forEach(c => c.dispose())
})
</script>

<style scoped>
.vote-card { margin-bottom: 18px; }
.vote-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.vote-header h4 { font-size: var(--font-md); }

.chart-wrap { position: relative; height: 240px; margin-bottom: 12px; }
.chart-box { width: 100%; height: 100%; }
.chart-total {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  text-align: center; pointer-events: none;
}
.total-num { display: block; font-size: 28px; font-weight: 700; color: var(--text-primary); }
.total-label { font-size: var(--font-sm); color: var(--text-dim); }

.cast-section { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.cast-options { display: flex; gap: 8px; }
.cast-btn.selected { border-color: var(--gold); color: var(--gold); box-shadow: 0 0 10px var(--gold-glow); }

.close-btn { margin-top: 10px; }

</style>
