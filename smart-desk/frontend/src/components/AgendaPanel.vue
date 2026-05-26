<template>
  <div class="panel">
    <div class="section-head">
      <h3>会议议程</h3>
      <div style="display:flex;gap:8px">
        <button v-if="isAdmin" class="btn-primary btn-sm" @click="showAdd = true">+ 添加</button>
        <button class="btn-ghost btn-sm" @click="$emit('close')">✕</button>
      </div>
    </div>

    <div v-if="!agendas.length" class="empty-sm">暂无议程</div>

    <div v-else class="agenda-list">
      <div v-for="a in agendas" :key="a.id" class="card agenda-item">
        <span class="order">{{ a.sort_order + 1 }}</span>
        <span class="text">{{ a.title }}</span>
        <button v-if="isAdmin" class="btn-ghost btn-sm" @click="remove(a.id)">删除</button>
      </div>
    </div>

    <div v-if="showAdd" class="inline-form">
      <input v-model="title" placeholder="议程内容" @keyup.enter="add" />
      <button class="btn-primary btn-sm" @click="add">确认</button>
      <button class="btn-ghost btn-sm" @click="showAdd = false">取消</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { api } from '../api/index.js'

const isAdmin = inject('isAdmin')
const props = defineProps({ meetingId: Number })
defineEmits(['close'])

const agendas = ref([])
const showAdd = ref(false)
const title = ref('')

onMounted(async () => {
  agendas.value = await api.listAgendas(props.meetingId)
})

async function add() {
  if (!title.value.trim()) return
  const a = await api.addAgenda(props.meetingId, { title: title.value, sort_order: agendas.value.length })
  agendas.value.push(a)
  title.value = ''
  showAdd.value = false
}

async function remove(id) {
  await api.removeAgenda(props.meetingId, id)
  agendas.value = agendas.value.filter(a => a.id !== id)
}
</script>

<style scoped>
.agenda-item {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 8px;
  padding: 14px 20px;
}
.order {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-sm);
  font-weight: 600;
  flex-shrink: 0;
}
.text { flex: 1; }
.inline-form { display: flex; gap: 8px; margin-top: 12px; }
.inline-form input { flex: 1; }
</style>
