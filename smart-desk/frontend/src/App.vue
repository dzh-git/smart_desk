<template>
  <div class="app-shell">
    <header class="top-bar">
      <div class="logo" @click="$router.push('/')" role="link" tabindex="0" aria-label="返回首页">
        <div class="logo-mark">
          <span class="logo-icon">◈</span>
        </div>
        <span class="logo-text">SmartDesk</span>
      </div>
      <div class="top-bar-right">
        <span class="time-display">{{ timeStr }}</span>
        <span class="ws-indicator" :class="{ connected: wsConnected }" title="连接状态"></span>
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
const wsConnected = ref(false)
provide('appConnected', wsConnected)

let timer = null
function tick() {
  const d = new Date()
  timeStr.value = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
onMounted(() => { tick(); timer = setInterval(tick, 5000) })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.app-shell { height: 100%; display: flex; flex-direction: column; }

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  height: 56px;
  background: rgba(15, 15, 26, 0.8);
  backdrop-filter: blur(16px) saturate(150%);
  -webkit-backdrop-filter: blur(16px) saturate(150%);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
  z-index: 60;
}
.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
}
.logo-mark {
  width: 34px; height: 34px;
  border-radius: var(--radius-sm);
  background: linear-gradient(135deg, var(--accent), var(--violet));
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 16px var(--accent-glow);
}
.logo-icon { font-size: 18px; color: #fff; }
.logo-text {
  font-size: var(--font-lg);
  font-weight: 700;
  letter-spacing: 0.5px;
  background: linear-gradient(135deg, var(--text-primary), var(--text-secondary));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.top-bar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.time-display {
  font-size: var(--font-sm);
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.03em;
}
.ws-indicator {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--text-dim);
  transition: all 0.3s var(--ease-out);
}
.ws-indicator.connected {
  background: var(--success);
  box-shadow: 0 0 8px var(--success-glow);
}

.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
}
</style>
