<template>
  <div class="panel">
    <div class="section-head">
      <h3>参会者管理</h3>
      <button v-if="isAdmin" class="btn-primary btn-sm" @click="showAdd = true">+ 添加</button>
    </div>

    <div v-if="!attendees.length" class="empty-sm">暂无参会者</div>

    <div class="attendee-grid">
      <div
        v-for="a in attendees" :key="a.id"
        class="card attendee-card"
        :class="{ checked: a.checked_in, self: a.seat_id === seatId }"
      >
        <div class="attendee-avatar">{{ a.name[0] }}</div>
        <div class="attendee-info">
          <div class="name">{{ a.name }} <span v-if="a.seat_id === seatId" class="self-tag">我</span></div>
          <div class="title">{{ a.title || '参会者' }} · 座位 {{ a.seat_id }}</div>
        </div>
        <div class="attendee-status">
          <span v-if="a.checked_in" class="badge badge-active">已签到</span>
          <span v-else class="badge badge-pending">未签到</span>
        </div>
        <button v-if="!a.checked_in && (isAdmin || a.seat_id === seatId)" class="btn-gold btn-sm" @click="doCheckin(a)">签到</button>
        <button v-if="isAdmin" class="btn-ghost btn-sm" @click="removeAttendee(a.id)">删除</button>
      </div>
    </div>

    <!-- Add dialog -->
    <BaseDialog v-model="showAdd" title="添加参会者">
      <label>姓名</label>
      <input v-model="form.name" placeholder="姓名" />
      <label>职位</label>
      <input v-model="form.title" placeholder="职位（可选）" />
      <label>RFID卡号</label>
      <input v-model="form.rfid_card" placeholder="卡号（可选）" />
      <label>座位号</label>
      <input v-model.number="form.seat_id" type="number" placeholder="1" />
      <template #actions>
        <button class="btn-ghost" @click="showAdd = false">取消</button>
        <button class="btn-primary" @click="doAdd" :disabled="!form.name.trim()">添加</button>
      </template>
    </BaseDialog>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, inject } from 'vue'
import { api } from '../api/index.js'
import BaseDialog from './shared/BaseDialog.vue'

const seatId = inject('seatId')
const isAdmin = inject('isAdmin')
const props = defineProps({ meetingId: Number, wsMsg: Object })

const attendees = ref([])
const showAdd = ref(false)
const form = ref({ name: '', title: '', rfid_card: '', seat_id: seatId.value })

onMounted(load)

async function load() {
  attendees.value = await api.listAttendees(props.meetingId)
}

async function doAdd() {
  if (!form.value.name.trim()) return
  await api.addAttendee(props.meetingId, form.value)
  showAdd.value = false
  form.value = { name: '', title: '', rfid_card: '', seat_id: seatId.value }
  await load()
}

async function removeAttendee(id) {
  await api.removeAttendee(props.meetingId, id)
  attendees.value = attendees.value.filter(a => a.id !== id)
}

async function doCheckin(a) {
  await api.checkin(props.meetingId, { rfid_card: a.rfid_card })
  a.checked_in = true
}

// WS: external checkin
watch(() => props.wsMsg, (msg) => {
  if (msg?.type === 'checkin') {
    const a = attendees.value.find(x => x.id === msg.data.attendee_id)
    if (a) a.checked_in = true
  }
})
</script>

<style scoped>
.attendee-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.attendee-card { display: flex; align-items: center; gap: 14px; padding: 16px 20px; border-left: 3px solid transparent; transition: all 0.3s; }
.attendee-card.checked { border-left-color: var(--success); }
.attendee-card.self { border-left-color: var(--accent); }
.attendee-avatar {
  width: 40px; height: 40px; border-radius: 50%;
  background: var(--accent); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-weight: 600; font-size: var(--font-md); flex-shrink: 0;
}
.attendee-info { flex: 1; min-width: 0; }
.name { font-weight: 600; }
.self-tag { display: inline-block; font-size: 11px; background: var(--accent); color: #fff; padding: 1px 6px; border-radius: 8px; margin-left: 4px; vertical-align: middle; }
.title { font-size: var(--font-sm); color: var(--text-secondary); }

</style>
