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
  const json = await res.json()
  return json.data !== undefined ? json.data : json
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
  setSpeakerSeat: (seatId, meetingId = null) => request('POST', '/seats/speaker', { seat_id: seatId, meeting_id: meetingId }),
  clearSpeakerSeat: (meetingId = null) => request('DELETE', meetingId ? `/seats/speaker?meeting_id=${meetingId}` : '/seats/speaker'),

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
    return fetch(`${BASE}/translations/audio`, { method: 'POST', body: form }).then(async r => {
      if (!r.ok) {
        const err = await r.json().catch(() => ({ message: r.statusText }))
        throw new Error(err.message || err.detail || r.statusText)
      }
      return r.json().then(json => json.data !== undefined ? json.data : json)
    })
  },

  // ── Dashboard ──
  getDashboard: (meetingId) => request('GET', `/dashboard?meeting_id=${meetingId}`),
}
