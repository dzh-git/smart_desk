# Task 018: ConnectionLostOverlay.vue + WebSocket Reconnection

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Vue 3, Vite, WebSocket

## Task Objective

Add `ConnectionLostOverlay.vue` — a semi-transparent overlay shown when WebSocket disconnects (migration C1). Updates `App.vue` to provide `appConnected` reactive state. The overlay blocks interactive operations (vote, service call) while allowing read-only viewing of cached data. Auto-reconnects every 3 seconds.

This is Task 18 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\frontend\src\components\ConnectionLostOverlay.vue`
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\App.vue`
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\composables\useWebSocket.js`

- [ ] **Step 1: Create ConnectionLostOverlay.vue**

```vue
<template>
  <Teleport to="body">
    <div v-if="!connected" class="connection-lost-overlay">
      <div class="connection-lost-card">
        <div class="spinner"></div>
        <p>Connection Lost</p>
        <p class="sub">Reconnecting every 3 seconds...</p>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
defineProps({ connected: Boolean })
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
```

- [ ] **Step 2: Update useWebSocket.js for appConnected state**

In `composables/useWebSocket.js`, add `appConnected` reactive ref and auto-reconnect logic:
```javascript
import { ref, readonly } from 'vue'

const appConnected = ref(false)

export function useWebSocket(meetingId, seat) {
  // ... existing connection setup ...

  // On open: appConnected.value = true
  // On close/error: appConnected.value = false, schedule reconnect after 3s

  // Auto-reconnect loop (3s interval)
  function scheduleReconnect() {
    setTimeout(() => {
      if (!appConnected.value) {
        connect()
      }
    }, 3000)
  }

  return {
    // ... existing ...
    appConnected: readonly(appConnected),
  }
}
```

- [ ] **Step 3: Update App.vue to provide appConnected and show overlay**

In `App.vue`:
```vue
<template>
  <div id="app-wrapper">
    <ConnectionLostOverlay :connected="appConnected" />
    <router-view />
  </div>
</template>

<script setup>
import { provide } from 'vue'
import ConnectionLostOverlay from './components/ConnectionLostOverlay.vue'
// ... get appConnected from useWebSocket or MeetingView
provide('appConnected', appConnected)
</script>
```

- [ ] **Step 4: Block interactive operations when disconnected**

In `VotingPanel.vue` and `ServicePanel.vue`, add guards:
```javascript
const appConnected = inject('appConnected')

async function handleVote() {
  if (!appConnected.value) return  // blocked
  // ... actual vote logic
}
```

- [ ] **Step 5: Verify overlay works**

Start the frontend dev server, stop the backend, verify the overlay appears. Restart backend, verify it disappears and reconnects.
