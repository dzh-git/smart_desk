const BASE = '/api'

async function request(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body) opts.body = JSON.stringify(body)
  const res = await fetch(`${BASE}${path}`, opts)
  if (res.status === 204) return null
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export const api = {
  // meetings
  listMeetings: () => request('GET', '/meetings'),
  createMeeting: (data) => request('POST', '/meetings', data),
  getMeeting: (id) => request('GET', `/meetings/${id}`),
  updateMeeting: (id, data) => request('PATCH', `/meetings/${id}`, data),
  deleteMeeting: (id) => request('DELETE', `/meetings/${id}`),

  // agendas
  listAgendas: (mid) => request('GET', `/meetings/${mid}/agendas`),
  addAgenda: (mid, data) => request('POST', `/meetings/${mid}/agendas`, data),
  removeAgenda: (mid, aid) => request('DELETE', `/meetings/${mid}/agendas/${aid}`),

  // attendees
  listAttendees: (mid) => request('GET', `/meetings/${mid}/attendees`),
  addAttendee: (mid, data) => request('POST', `/meetings/${mid}/attendees`, data),
  removeAttendee: (mid, aid) => request('DELETE', `/meetings/${mid}/attendees/${aid}`),

  // checkin (seat-based, no RFID)
  checkin: (mid, seatId) => request('POST', `/checkin/${mid}`, { seat_id: seatId }),

  // votes
  listVotes: (mid) => request('GET', `/votes/${mid}`),
  createVote: (mid, data) => request('POST', `/votes/${mid}`, data),
  getVote: (mid, vid) => request('GET', `/votes/${mid}/${vid}`),
  castVote: (mid, vid, data) => request('POST', `/votes/${mid}/${vid}/cast`, data),
  closeVote: (mid, vid) => request('POST', `/votes/${mid}/${vid}/close`),

  // service calls
  listServiceCalls: (mid) => request('GET', `/service-calls/${mid}`),
  createServiceCall: (mid, data) => request('POST', `/service-calls/${mid}`, data),
  updateCallStatus: (mid, cid, data) => request('PATCH', `/service-calls/${mid}/${cid}`, data),

  // translation
  translate: (data) => request('POST', '/translate', data),
  preloadModels: () => request('POST', '/translate/preload'),
  getPreloadStatus: () => request('GET', '/translate/preload/status'),
  setSpeakerSeat: (meetingId, seatId) => request('POST', '/translate/speaker-seat', {
    meeting_id: meetingId, seat_id: seatId,
  }),
  getSpeakerSeat: (meetingId) => request('GET', `/translate/speaker-seat?meeting_id=${meetingId}`),
  getTranscriptHistory: (meetingId) => request('GET', `/translate/history?meeting_id=${meetingId}`),
  uploadAudio: (meetingId, seatId, blob, isFinal = true) => {
    const form = new FormData()
    form.append('meeting_id', meetingId)
    form.append('seat_id', seatId)
    form.append('final', isFinal)
    form.append('audio', blob, 'recording.wav')
    return fetch('/api/translate/audio', { method: 'POST', body: form }).then(r => {
      if (!r.ok) throw new Error('Upload failed')
      return r.json()
    })
  },
}
