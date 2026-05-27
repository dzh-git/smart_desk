<template>
  <div class="overlay" @click.self="$emit('close')" @keydown.escape="$emit('close')">
    <div class="dialog card checkin-dialog">
      <h2>确认加入会议？</h2>
      <p class="sub">座位 {{ seatId }} · 点击确认完成签到</p>
      <div class="checkin-actions">
        <button class="btn-ghost" @click="$emit('close')">取消</button>
        <button class="btn-gold" @click="confirm" :disabled="loading">
          {{ loading ? '签到中…' : '确认签到' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api/index.js'

const props = defineProps({ seatId: Number, meetingId: Number })
const emit = defineEmits(['close', 'confirmed'])

const loading = ref(false)

async function confirm() {
  loading.value = true
  try {
    await api.checkin(props.meetingId, props.seatId)
    emit('confirmed', props.seatId)
  } catch (e) {
    console.error('Check-in failed:', e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.checkin-dialog {
  text-align: center;
  padding: 36px;
}
.checkin-dialog h2 {
  font-size: var(--font-xl);
  margin-bottom: 8px;
}
.sub {
  color: var(--text-secondary);
  font-size: var(--font-md);
  margin-bottom: 24px;
}
.checkin-actions {
  display: flex;
  justify-content: center;
  gap: 14px;
}
</style>
