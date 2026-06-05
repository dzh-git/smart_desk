<template>
  <Teleport to="body">
    <div v-if="enabled && !connected" class="connection-lost-overlay">
      <div class="connection-lost-card">
        <div class="spinner"></div>
        <p>Connection Lost</p>
        <p class="sub">Reconnecting every 3 seconds...</p>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
defineProps({
  connected: Boolean,
  enabled: { type: Boolean, default: true },
})
</script>

<style scoped>
.connection-lost-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.7);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}
.connection-lost-card {
  background: #1e1e2e;
  border: 1px solid #ff6b6b;
  border-radius: 12px;
  padding: 32px 48px;
  text-align: center;
  color: #fff;
}
.spinner {
  width: 40px; height: 40px;
  border: 3px solid #444;
  border-top-color: #ff6b6b;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 16px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.sub { color: #aaa; font-size: 14px; margin-top: 8px; }
</style>

