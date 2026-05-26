<template>
  <div class="app-shell">
    <header class="top-bar">
      <div class="logo" @click="$router.push('/')">
        <span class="logo-icon">◈</span>
        <span class="logo-text">SmartDesk</span>
      </div>
      <div class="top-bar-right">
        <span class="time-display">{{ timeStr }}</span>
      </div>
    </header>
    <main class="main-content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, provide } from 'vue'
import { useSeat } from './composables/useSeat.js'

const { seatId, isAdmin } = useSeat()
provide('seatId', seatId)
provide('isAdmin', isAdmin)

const timeStr = ref('')
let timer = null
function tick() {
  const d = new Date()
  timeStr.value = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
onMounted(() => { tick(); timer = setInterval(tick, 1000) })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.app-shell { height: 100%; display: flex; flex-direction: column; }

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  height: 56px;
  background: var(--bg-secondary);
  border-bottom: 1px solid rgba(255,255,255,0.05);
  flex-shrink: 0;
}
.logo { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.logo-icon { font-size: 22px; color: var(--accent); }
.logo-text { font-size: var(--font-lg); font-weight: 600; letter-spacing: 1px; }
.time-display { font-size: var(--font-md); color: var(--text-secondary); font-variant-numeric: tabular-nums; }

.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
}
</style>
