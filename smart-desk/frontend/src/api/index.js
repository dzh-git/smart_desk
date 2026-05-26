const BASE = '/api'

async function request(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body) opts.body = JSON.stringify(body)
  const res = await fetch(`${BASE}${path}`, opts)
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
  updateMeeting: (id, data) => request('PUT', `/meetings/${id}`, data),
  deleteMeeting: (id) => request('DELETE', `/meetings/${id}`),

  // agendas
  listAgendas: (mid) => request('GET', `/meetings/${mid}/agendas`),
  addAgenda: (mid, data) => request('POST', `/meetings/${mid}/agendas`, data),
  removeAgenda: (mid, aid) => request('DELETE', `/meetings/${mid}/agendas/${aid}`),

  // attendees
  listAttendees: (mid) => request('GET', `/meetings/${mid}/attendees`),
  addAttendee: (mid, data) => request('POST', `/meetings/${mid}/attendees`, data),
  removeAttendee: (mid, aid) => request('DELETE', `/meetings/${mid}/attendees/${aid}`),
  checkin: (mid, data) => request('POST', `/meetings/${mid}/checkin`, data),

  // votes
  listVotes: (mid) => request('GET', `/votes/meeting/${mid}`),
  createVote: (mid, data) => request('POST', `/votes?meeting_id=${mid}`, data),
  getVote: (vid) => request('GET', `/votes/${vid}`),
  castVote: (vid, data) => request('POST', `/votes/${vid}/cast`, data),
  closeVote: (vid) => request('POST', `/votes/${vid}/close`),

  // services
  listServiceCalls: (mid) => request('GET', `/services/meeting/${mid}`),
  createServiceCall: (mid, data) => request('POST', `/services?meeting_id=${mid}`, data),
  updateCallStatus: (cid, status) => request('PUT', `/services/${cid}/status?status=${status}`),

  // translation
  translate: (data) => request('POST', '/translate', data),
}
