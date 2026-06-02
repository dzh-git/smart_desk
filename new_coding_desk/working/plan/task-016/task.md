# Task 016: Frontend API Paths Update

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Vue 3, Vite, JavaScript fetch API

## Task Objective

Update `frontend/src/api/index.js` to match the new backend API paths (migration B1). Old paths like `/api/translate/*` become `/api/translations/*`, checkin moves to `/api/seats/{id}/checkin`, speaker seat to `/api/seats/speaker`. Add new API methods for start/end meeting, get active meeting, dashboard, vote statistics, service call resolve/cancel.

This is Task 16 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\frontend\src\api\index.js`

- [ ] **Step 1: Rewrite api/index.js**

```javascript
const BASE = '/api'

async function request(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body) opts.body = JSON.stringify(body)
  const res = await fetch(`${BASE}${path}`, opts)
  if (res.status === 204) return null
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }))
    throw new Error(err.message || err.detail || res.statusText)
  }
  return res.json()
}

export const api = {
  // ── Meetings ──
  listMeetings: () => request('GET', '/meetings'),
  createMeeting: (data) => request('POST', '/meetings', data),
  getMeeting: (id) => request('GET', `/meetings/${id}`),
  updateMeeting: (id, data) => request('PATCH', `/meetings/${id}`, data),
  deleteMeeting: (id) => request('DELETE', `/meetings/${id}`),
  getActiveMeeting: () => request('GET', '/meetings/active'),
  startMeeting: (id) => request('POST', `/meetings/${id}/start`),
  endMeeting: (id) => request('POST', `/meetings/${id}/end`),

  // ── Agendas ──
  listAgendas: (mid) => request('GET', `/meetings/${mid}/agendas`),
  addAgenda: (mid, data) => request('POST', `/meetings/${mid}/agendas`, data),
  removeAgenda: (mid, aid) => request('DELETE', `/meetings/${mid}/agendas/${aid}`),

  // ── Attendees ──
  listAttendees: (mid) => request('GET', `/meetings/${mid}/attendees`),
  addAttendee: (mid, data) => request('POST', `/meetings/${mid}/attendees`, data),
  removeAttendee: (mid, aid) => request('DELETE', `/meetings/${mid}/attendees/${aid}`),

  // ── Seats (was checkin) ──
  listSeats: () => request('GET', '/seats'),
  checkin: (seatId, attendeeId) => request('POST', `/seats/${seatId}/checkin`, { attendee_id: attendeeId }),
  getSpeakerSeat: () => request('GET', '/seats/speaker'),
  setSpeakerSeat: (seatId) => request('POST', '/seats/speaker', { seat_id: seatId }),
  clearSpeakerSeat: () => request('DELETE', '/seats/speaker'),

  // ── Votes ──
  getActiveVote: (meetingId) => request('GET', `/votes/active?meeting_id=${meetingId}`),
  createVote: (data) => request('POST', '/votes', data),
  getVote: (vid) => request('GET', `/votes/${vid}`),
  castVote: (vid, data) => request('POST', `/votes/${vid}/submit`, data),
  closeVote: (vid) => request('POST', `/votes/${vid}/close`),
  getVoteStatistics: (vid) => request('GET', `/votes/${vid}/statistics`),

  // ── Service Calls ──
  listServiceCalls: (meetingId) => request('GET', `/service-calls?meeting_id=${meetingId}`),
  createServiceCall: (meetingId, data) => request('POST', `/service-calls?meeting_id=${meetingId}`, data),
  getCurrentCall: (meetingId, seatId) => request('GET', `/service-calls/current?meeting_id=${meetingId}&seat_id=${seatId}`),
  resolveServiceCall: (cid) => request('POST', `/service-calls/${cid}/resolve`),
  cancelServiceCall: (cid) => request('POST', `/service-calls/${cid}/cancel`),

  // ── Translations (renamed paths) ──
  translateText: (data) => request('POST', '/translations', data),
  getPreloadStatus: () => request('GET', '/translations/preload/status'),
  triggerPreload: () => request('POST', '/translations/preload'),
  getTranslationHistory: (meetingId) => request('GET', `/translations?meeting_id=${meetingId}`),
  uploadAudio: (meetingId, seatId, blob, isFinal = true, utteranceId = 0) => {
    const form = new FormData()
    form.append('meeting_id', meetingId)
    form.append('seat_id', seatId)
    form.append('final', isFinal)
    form.append('utterance_id', utteranceId)
    form.append('audio', blob, 'recording.wav')
    return fetch(`${BASE}/translations/audio`, { method: 'POST', body: form }).then(r => {
      if (!r.ok) throw new Error('Upload failed')
      return r.json()
    })
  },

  // ── Dashboard ──
  getDashboard: (meetingId) => request('GET', `/dashboard?meeting_id=${meetingId}`),
}
```

- [ ] **Step 2: Update VotingPanel.vue API calls**

Search for all uses of old API paths in Vue components and update:
- `api.castVote(mid, vid, data)` → `api.castVote(vid, data)`
- `api.listVotes(mid)` → `api.getActiveVote(mid)`
- `api.createVote(mid, data)` → `api.createVote({...data, meeting_id: mid})`
- `api.closeVote(mid, vid)` → `api.closeVote(vid)`

Check files: `VotingPanel.vue`, `MeetingView.vue`

- [ ] **Step 3: Update ServicePanel.vue API calls**

- `api.createServiceCall(mid, data)` → `api.createServiceCall(mid, data)`
- `api.updateCallStatus(mid, cid, data)` → `api.resolveServiceCall(cid)` or `api.cancelServiceCall(cid)`

Check file: `ServicePanel.vue`

- [ ] **Step 4: Update TranslationPanel.vue API calls**

- `api.setSpeakerSeat(mid, sid)` → `api.setSpeakerSeat(sid)`
- `api.getSpeakerSeat(mid)` → `api.getSpeakerSeat()`
- `api.getTranscriptHistory(mid)` → `api.getTranslationHistory(mid)`
- `api.translate(data)` → `api.translateText(data)`
- `api.uploadAudio(mid, seatId, blob, final, uttId)` → same but uses new base path internally

Check file: `TranslationPanel.vue`

- [ ] **Step 5: Update MeetingView.vue API calls**

- `api.checkin(mid, seatId)` → `api.checkin(seatId, attendeeId)` (requires attendee_id now)
- Add `api.startMeeting(id)` and `api.endMeeting(id)` usage
- `api.getMeeting(id)` still works

Check file: `MeetingView.vue`

- [ ] **Step 6: Verify frontend builds**

```bash
cd D:\learning\smart_desktop\smart-desk\frontend && npx vite build
```
Expected: Build succeeds with no errors
