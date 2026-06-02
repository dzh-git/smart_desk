# Task 017: Frontend WebSocket Event Names Update

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Vue 3, Vite, WebSocket

## Task Objective

Update all frontend WebSocket event handling to use new event names per spec (migration B2): `vote_update` → `vote_updated`, `translation_result` → `translation_final`, `service_update` → split into `service_call_created`/`service_call_resolved`/`service_call_cancelled`. Update all Vue components that process WS messages.

This is Task 17 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\views\MeetingView.vue`
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\components\VotingPanel.vue`
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\components\ServicePanel.vue`
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\components\TranslationPanel.vue`
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\components\SeatGrid.vue`

- [ ] **Step 1: Audit current WS event usage**

Search all `.vue` and `.js` files for WS event type strings:
- `vote_update` → replace with `vote_updated`
- `vote_cast` → replace with `vote_updated`
- `translation_result` → replace with `translation_final`
- `service_update` → replace with context-appropriate `service_call_created` / `service_call_resolved` / `service_call_cancelled`

Run to find occurrences:
```bash
cd D:\learning\smart_desktop\smart-desk\frontend\src && grep -rn "vote_update\|vote_cast\|translation_result\|service_update" --include="*.vue" --include="*.js"
```

- [ ] **Step 2: Update MeetingView.vue**

In the `lastWsMsg` watch or message handler, update event name comparisons:
```javascript
// OLD:
case 'vote_update':
// NEW:
case 'vote_updated':

// OLD:
case 'translation_result':
// NEW:
case 'translation_final':

// OLD:
case 'service_update':
// NEW: handle all three:
case 'service_call_created':
case 'service_call_resolved':
case 'service_call_cancelled':
```

- [ ] **Step 3: Update VotingPanel.vue**

Any references to `vote_update` or `vote_cast` in emitted events or message handling → change to `vote_updated`.

- [ ] **Step 4: Update ServicePanel.vue**

Split `service_update` handling into three separate handlers for `service_call_created`, `service_call_resolved`, `service_call_cancelled`. Each triggers a refresh of the service call list.

- [ ] **Step 5: Update TranslationPanel.vue**

Change `translation_result` handling to `translation_final`.

- [ ] **Step 6: Update SeatGrid.vue**

Check for any WS event handling (seat_occupied, seat_vacant, check_in, checkin_prompt, speaker_seat_set, speaker_seat_clear) — these names are unchanged per spec, but verify they still work.

- [ ] **Step 7: Update useWebSocket.js if needed**

Check `composables/useWebSocket.js` for any hardcoded event type strings used in filtering or dispatching. Update if present.

- [ ] **Step 8: Verify frontend builds**

```bash
cd D:\learning\smart_desktop\smart-desk\frontend && npx vite build
```
Expected: Build succeeds
