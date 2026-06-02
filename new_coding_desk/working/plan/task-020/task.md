# Task 020: Speaker Seat Switch Interrupts Recording

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, Vue 3

## Task Objective

Implement migration item C8: when speaker seat switches, immediately interrupt the current recording and discard unfinished audio. The `speaker_seat_set` event must trigger recording reset on the old speaker's tablet via the EventBus. The `speaker_seat_clear` event also stops recording.

This is Task 20 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\backend\services\seat_service.py`
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\components\TranslationPanel.vue`
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\composables\useAudioRecorder.js`

- [ ] **Step 1: Update SeatService.set_speaker_seat to signal recording stop**

In `backend/services/seat_service.py`, enhance `set_speaker_seat`:
```python
def set_speaker_seat(self, meeting_id: int, seat_id: int):
    """Set speaker seat. Includes recording_stop signal for previous speaker."""
    current = self.seat_repo.get_speaker_seat()
    previous_seat_id = current.seat_id if current else None

    # Publish recording_stop for previous speaker
    if previous_seat_id and previous_seat_id != seat_id:
        self.bus.publish(BaseEvent(
            name="recording_stop",
            payload={"seat_id": previous_seat_id, "reason": "speaker_changed"},
        ))

    sp = self.seat_repo.set_speaker_seat(seat_id)
    self.bus.publish(BaseEvent(
        name="speaker_seat_set",
        payload={"seat_id": seat_id},
    ))
    return sp
```

- [ ] **Step 2: Update clear_speaker_seat to also signal recording stop**

```python
def clear_speaker_seat(self, meeting_id: int):
    current = self.seat_repo.get_speaker_seat()
    if current and current.seat_id:
        self.bus.publish(BaseEvent(
            name="recording_stop",
            payload={"seat_id": current.seat_id, "reason": "speaker_cleared"},
        ))
    sp = self.seat_repo.clear_speaker_seat()
    self.bus.publish(BaseEvent(
        name="speaker_seat_clear",
        payload={},
    ))
    return sp
```

- [ ] **Step 3: Register recording_stop in WS EventBridge**

In `backend/services/ws_event_bridge.py`, add `recording_stop` to `EVENT_TO_WS_TYPE`:
```python
EVENT_TO_WS_TYPE = {
    # ... existing ...
    "recording_stop": "recording_stop",
}
```

- [ ] **Step 4: Update TranslationPanel.vue to handle recording_stop WS event**

In `TranslationPanel.vue`, add a handler for the `recording_stop` event:
```javascript
// In WS message handler
if (msg.type === 'recording_stop' && msg.payload.seat_id === seatId.value) {
  // Abort current recording
  stopRecording()
  // Reset interim display
  clearTranscript()
}
```

- [ ] **Step 5: Update useAudioRecorder.js with stop method**

In `composables/useAudioRecorder.js`, ensure there is a public `stop()` method that:
- Stops the MediaRecorder
- Clears any pending interim timer
- Resets VAD state
- Does NOT send any final audio (discards)

```javascript
function stop() {
  if (mediaRecorder.value && mediaRecorder.value.state !== 'inactive') {
    mediaRecorder.value.stop()
  }
  clearTimeout(interimTimer)
  // Reset VAD state
  vadState.reset()
  // Discard any buffered audio
  audioChunks = []
}
```

- [ ] **Step 6: Verify behavior**

Manual verification on a running system:
1. Set speaker seat to 5 → Seat 5 starts recording
2. Set speaker seat to 3 → Seat 5 receives `recording_stop` and stops recording
3. Seat 3 starts fresh recording
