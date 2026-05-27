<template>
  <div class="home">
    <div class="home-header">
      <div>
        <h1>会议列表</h1>
        <p class="header-sub" v-if="!loading">共 {{ meetings.length }} 个会议</p>
      </div>
      <button class="btn-primary" @click="showCreate = true" aria-label="创建新会议">
        <span class="create-icon">+</span>
        创建会议
      </button>
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="meeting-grid">
      <div v-for="i in 4" :key="i" class="card skeleton-card">
        <div class="skeleton" style="width:60%;height:22px;margin-bottom:12px;"></div>
        <div class="skeleton" style="width:90%;height:14px;margin-bottom:8px;"></div>
        <div class="skeleton" style="width:40%;height:12px;"></div>
      </div>
    </div>

    <!-- Empty -->
    <div v-else-if="!meetings.length" class="empty">
      <div class="empty-icon">◈</div>
      <p class="empty-title">暂无会议</p>
      <p class="empty-sub">点击右上角「创建会议」开始</p>
    </div>

    <!-- Meeting cards -->
    <div v-else class="meeting-grid">
      <div
        v-for="m in meetings" :key="m.id"
        class="card meeting-card"
        :class="{ active: m.status === 'active' }"
        role="link"
        tabindex="0"
        @click="$router.push(`/meeting/${m.id}`)"
        @keydown.enter="$router.push(`/meeting/${m.id}`)"
      >
        <div class="card-accent" :class="m.status"></div>
        <div class="card-top">
          <h3>{{ m.title }}</h3>
          <span class="badge" :class="statusClass(m.status)">{{ statusLabel(m.status) }}</span>
        </div>
        <p class="desc">{{ m.description || '暂无描述' }}</p>
        <div class="card-foot">
          <span class="card-date">{{ formatDate(m.created_at) }}</span>
          <span class="card-arrow">→</span>
        </div>
      </div>
    </div>

    <!-- Create dialog -->
    <BaseDialog v-model="showCreate" title="创建会议">
      <label for="meeting-title">会议名称</label>
      <input id="meeting-title" v-model="form.title" placeholder="输入会议名称" />
      <label for="meeting-desc">描述（可选）</label>
      <textarea id="meeting-desc" v-model="form.description" placeholder="会议描述" rows="3"></textarea>
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

.home-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 32px;
}
.home-header h1 { font-size: var(--font-2xl); font-weight: 700; }
.header-sub { font-size: var(--font-sm); color: var(--text-dim); margin-top: 4px; }
.create-icon { font-size: 18px; font-weight: 300; margin-right: 2px; }

/* Cards grid */
.meeting-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.meeting-card {
  cursor: pointer;
  position: relative;
  overflow: hidden;
  padding: 24px;
  outline: none;
}
.meeting-card:focus-visible {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}

/* Accent stripe */
.card-accent {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--border-subtle);
  transition: all 0.3s var(--ease-out);
}
.card-accent.active { background: linear-gradient(90deg, var(--success), var(--accent)); }
.card-accent.done, .card-accent.finished { background: linear-gradient(90deg, var(--text-dim), var(--text-secondary)); }
.card-accent.pending { background: linear-gradient(90deg, var(--gold), var(--gold-light)); }

.meeting-card:hover .card-accent {
  height: 4px;
  background: linear-gradient(90deg, var(--accent), var(--violet));
}
.meeting-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  margin-top: 4px;
}
.card-top h3 {
  font-size: var(--font-lg);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 8px;
}
.desc {
  color: var(--text-secondary);
  font-size: var(--font-sm);
  margin-bottom: 16px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--font-xs);
  color: var(--text-dim);
}
.card-arrow {
  font-size: 18px;
  color: var(--text-dim);
  transition: all 0.3s var(--ease-out);
}
.meeting-card:hover .card-arrow {
  color: var(--accent);
  transform: translateX(4px);
}

/* Skeleton */
.skeleton-card {
  padding: 24px;
  min-height: 140px;
}

/* Empty */
.empty {
  text-align: center;
  padding: 100px 0;
}
.empty-icon {
  font-size: 48px;
  color: var(--text-dim);
  margin-bottom: 16px;
  opacity: 0.4;
}
.empty-title {
  font-size: var(--font-lg);
  color: var(--text-secondary);
  font-weight: 500;
  margin-bottom: 6px;
}
.empty-sub {
  font-size: var(--font-sm);
  color: var(--text-dim);
}
</style>
