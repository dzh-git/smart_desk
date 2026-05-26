<template>
  <div class="home">
    <div class="home-header">
      <h1>会议列表</h1>
      <button class="btn-primary" @click="showCreate = true">+ 创建会议</button>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!meetings.length" class="empty">
      <p>暂无会议</p>
      <p class="sub">点击右上角创建第一个会议</p>
    </div>

    <div v-else class="meeting-grid">
      <div
        v-for="m in meetings" :key="m.id"
        class="card meeting-card"
        @click="$router.push(`/meeting/${m.id}`)"
      >
        <div class="card-top">
          <h3>{{ m.title }}</h3>
          <span class="badge" :class="statusClass(m.status)">{{ statusLabel(m.status) }}</span>
        </div>
        <p class="desc">{{ m.description || '暂无描述' }}</p>
        <div class="card-foot">
          <span>{{ formatDate(m.created_at) }}</span>
          <span class="arrow">→</span>
        </div>
      </div>
    </div>

    <!-- Create dialog -->
    <BaseDialog v-model="showCreate" title="创建会议">
      <label>会议名称</label>
      <input v-model="form.title" placeholder="输入会议名称" />
      <label>描述（可选）</label>
      <textarea v-model="form.description" placeholder="会议描述" rows="3"></textarea>
      <template #actions>
        <button class="btn-ghost" @click="showCreate = false">取消</button>
        <button class="btn-primary" @click="doCreate" :disabled="!form.title.trim()">创建</button>
      </template>
    </BaseDialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/index.js'
import BaseDialog from '../components/shared/BaseDialog.vue'
import { statusClass, statusLabel } from '../utils/status.js'

const router = useRouter()
const meetings = ref([])
const loading = ref(true)
const showCreate = ref(false)
const form = ref({ title: '', description: '' })

onMounted(async () => {
  try { meetings.value = await api.listMeetings() } catch {}
  loading.value = false
})

async function doCreate() {
  if (!form.value.title.trim()) return
  const m = await api.createMeeting({ title: form.value.title, description: form.value.description })
  showCreate.value = false
  form.value = { title: '', description: '' }
  router.push(`/meeting/${m.id}`)
}

function formatDate(d) {
  return new Date(d).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.home { max-width: 960px; margin: 0 auto; }
.home-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 28px; }
.home-header h1 { font-size: var(--font-xl); font-weight: 600; }

.meeting-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; }
.meeting-card { cursor: pointer; }
.meeting-card:hover { border-color: var(--accent); }
.card-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.card-top h3 { font-size: var(--font-lg); font-weight: 600; }
.desc { color: var(--text-secondary); font-size: var(--font-sm); margin-bottom: 14px; line-height: 1.5; }
.card-foot { display: flex; justify-content: space-between; align-items: center; font-size: var(--font-sm); color: var(--text-dim); }
.arrow { font-size: 18px; color: var(--accent); }

.empty { text-align: center; padding: 80px 0; color: var(--text-secondary); }
.empty .sub { font-size: var(--font-sm); color: var(--text-dim); margin-top: 8px; }
.loading { text-align: center; padding: 80px 0; color: var(--text-dim); }
</style>
