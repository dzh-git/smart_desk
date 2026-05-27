<template>
  <Teleport to="body">
    <div v-if="visible" class="history-overlay" @click.self="$emit('close')">
      <div class="history-modal">
        <div class="history-head">
          <h3>历史发言记录</h3>
          <button class="btn-ghost" @click="$emit('close')" aria-label="关闭历史记录">✕</button>
        </div>
        <div class="history-body">
          <div
            v-for="item in items"
            :key="item.id"
            class="history-item"
          >
            <div class="history-meta">
              <span class="history-seat">座位 {{ item.seat_id }}</span>
              <span class="history-time">{{ fmtTs(item.ts) }}</span>
            </div>
            <div class="history-zh">{{ item.zh }}</div>
            <div class="history-en">{{ item.en }}</div>
          </div>
          <div v-if="!items.length" class="history-empty">暂无发言记录</div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
defineProps({
  visible: Boolean,
  items: { type: Array, default: () => [] },
})
defineEmits(['close'])

function fmtTs(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
</script>

<style scoped>
.history-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}
.history-modal {
  background: var(--bg-primary);
  border-radius: var(--radius-lg);
  width: 90vw;
  max-width: 560px;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.3);
}
.history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
.history-head h3 {
  margin: 0;
  font-size: var(--font-lg);
  color: var(--text-primary);
}
.history-head .btn-ghost {
  font-size: 18px;
  padding: 4px 8px;
}

.history-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}
.history-empty {
  text-align: center;
  padding: 40px 0;
  color: var(--text-dim);
  font-size: var(--font-sm);
}

.history-item {
  padding: 12px 16px;
  margin-bottom: 10px;
  background: var(--bg-card);
  border-radius: var(--radius);
  border-left: 3px solid var(--border-default);
}
.history-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.history-seat {
  font-size: var(--font-xs);
  color: var(--accent);
  background: rgba(91, 156, 230, 0.12);
  padding: 2px 10px;
  border-radius: 10px;
}
.history-time {
  font-size: var(--font-xs);
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}
.history-zh {
  font-size: var(--font-sm);
  color: var(--text-primary);
  line-height: 1.5;
  margin-bottom: 4px;
}
.history-en {
  font-size: var(--font-xs);
  color: var(--accent-light);
  line-height: 1.4;
  padding-top: 4px;
  border-top: 1px dashed var(--border-subtle);
}
</style>
