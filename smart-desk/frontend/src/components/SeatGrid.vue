<template>
  <div class="seat-grid">
    <div
      v-for="seat in seats" :key="seat.id"
      class="seat-card"
      :class="{
        occupied: seat.occupied,
        'checked-in': seat.checkedIn,
        self: seat.id === mySeat,
      }"
      :aria-label="seatLabel(seat)"
      role="button"
      tabindex="0"
      @click="onSeatClick(seat)"
      @keydown.enter="onSeatClick(seat)"
    >
      <!-- LED glow ring -->
      <div class="led-ring" :style="ledStyle(seat)"></div>

      <!-- Inner glow -->
      <div class="led-inner" :style="innerGlow(seat)"></div>

      <!-- Seat number -->
      <div class="seat-num" :class="{ dim: !seat.occupied }">{{ seat.id }}</div>

      <!-- State label -->
      <div class="seat-state">
        <span v-if="seat.checkedIn" class="state checked">✓ 已签到</span>
        <span v-else-if="seat.occupied" class="state occ">● 有人</span>
        <span v-else class="state empty">空位</span>
      </div>

      <!-- Attendee name -->
      <div class="seat-name" v-if="seat.name">{{ seat.name }}</div>

      <!-- Self tag -->
      <div v-if="seat.id === mySeat" class="my-tag">我</div>
    </div>

    <!-- Check-in modal -->
    <CheckInModal
      v-if="showCheckin"
      :seat-id="activeSeat"
      :meeting-id="meetingId"
      @close="showCheckin = false"
      @confirmed="onCheckedIn"
    />
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { useSeat } from '../composables/useSeat.js'
import { api } from '../api/index.js'
import CheckInModal from './CheckInModal.vue'

const { seatId: mySeat } = useSeat()
const props = defineProps({ meetingId: Number, wsMsg: Object })
const emit = defineEmits(['seat-click'])

function makeSeat(i) {
  return { id: i + 1, occupied: false, checkedIn: false, name: '', ledPattern: 'breathe', ledColor: [60, 70, 90] }
}
const seats = reactive(Array.from({ length: 8 }, (_, i) => makeSeat(i)))

const showCheckin = ref(false)
const activeSeat = ref(1)

function seatLabel(seat) {
  const state = seat.checkedIn ? '已签到' : seat.occupied ? '有人' : '空位'
  const name = seat.name ? ` ${seat.name}` : ''
  return `座位 ${seat.id} ${state}${name}`
}

onMounted(async () => {
  try {
    const attendees = await api.listAttendees(props.meetingId)
    for (const a of attendees) {
      if (a.seat_id >= 1 && a.seat_id <= 8) {
        const s = seats[a.seat_id - 1]
        s.occupied = true
        s.name = a.name
        if (a.checked_in) {
          s.checkedIn = true
          s.ledPattern = 'solid'
          s.ledColor = [255, 220, 180]
        } else {
          s.ledPattern = 'wave'
          s.ledColor = [91, 156, 230]
        }
      }
    }
  } catch {}
})

function ledStyle(seat) {
  const [r, g, b] = seat.ledColor
  const opacity = seat.checkedIn ? 0.7 : seat.occupied ? 0.5 : 0.08
  const innerOpacity = seat.checkedIn ? 0.3 : seat.occupied ? 0.2 : 0.04
  const anim = seat.occupied && !seat.checkedIn
    ? 'glow-pulse 2.5s ease-in-out infinite'
    : 'none'
  return {
    boxShadow: `
      0 0 16px rgba(${r},${g},${b},${opacity}),
      0 0 48px rgba(${r},${g},${b},${innerOpacity}),
      inset 0 0 16px rgba(${r},${g},${b},${innerOpacity * 0.5})
    `,
    borderColor: `rgba(${r},${g},${b},${opacity * 1.5})`,
    animation: anim,
  }
}

function innerGlow(seat) {
  const [r, g, b] = seat.ledColor
  const opacity = seat.checkedIn ? 0.08 : seat.occupied ? 0.05 : 0.01
  return {
    background: `radial-gradient(ellipse at center, rgba(${r},${g},${b},${opacity}) 0%, transparent 70%)`,
  }
}

function onSeatClick(seat) {
  activeSeat.value = seat.id
  if (!seat.checkedIn) {
    showCheckin.value = true
  }
  emit('seat-click', seat.id)
}

function onCheckedIn(seatId) {
  const s = seats.find(s => s.id === seatId)
  if (s) {
    s.checkedIn = true
    s.occupied = true
    s.ledPattern = 'solid'
    s.ledColor = [255, 220, 180]
  }
  showCheckin.value = false
}

watch(() => props.wsMsg, (msg) => {
  if (!msg) return
  const p = msg.payload || {}
  const sid = p.seat_id

  if (msg.type === 'seat_occupied' && sid) {
    const s = seats.find(s => s.id === sid)
    if (s) { s.occupied = true; s.ledPattern = 'wave'; s.ledColor = [91, 156, 230] }
  }
  if (msg.type === 'seat_vacant' && sid) {
    const s = seats.find(s => s.id === sid)
    if (s) { Object.assign(s, makeSeat(s.id - 1)) }
  }
  if (msg.type === 'check_in' && sid) {
    const s = seats.find(s => s.id === sid)
    if (s) { s.checkedIn = true; s.ledPattern = 'solid'; s.ledColor = [255, 220, 180] }
  }
  if (msg.type === 'vote_cast' && p.vote_id) {
    seats.forEach(s => { s.ledColor = [212, 176, 76]; s.ledPattern = 'solid' })
    setTimeout(() => {
      seats.forEach((s, i) => {
        if (s.checkedIn) s.ledColor = [255, 220, 180]
        else if (s.occupied) s.ledColor = [91, 156, 230]
        else s.ledColor = [60, 70, 90]
      })
    }, 2000)
  }
  if (msg.type === 'checkin_prompt' && sid) {
    activeSeat.value = sid
    showCheckin.value = true
  }
  if (msg.type === 'meeting_ended') {
    seats.forEach((s, i) => { Object.assign(s, makeSeat(i)) })
  }
})
</script>

<style scoped>
.seat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
}

.seat-card {
  position: relative;
  aspect-ratio: 1 / 1;
  max-height: 200px;
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  border: 2px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  transition: all 0.4s var(--ease-out);
  overflow: hidden;
  outline: none;
}
.seat-card:hover {
  background: var(--bg-card-hover);
  transform: translateY(-3px);
  border-color: var(--border-default);
  box-shadow: var(--shadow-md);
}
.seat-card:focus-visible {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}
.seat-card.self {
  border-color: rgba(91, 156, 230, 0.35);
}
.seat-card.checked-in {
  border-color: rgba(60, 184, 120, 0.3);
}

/* LED ring */
.led-ring {
  position: absolute;
  inset: 10px;
  border-radius: var(--radius-lg);
  border: 2px solid transparent;
  pointer-events: none;
  transition: all 0.6s var(--ease-out);
}

/* Inner ambient glow */
.led-inner {
  position: absolute;
  inset: 0;
  pointer-events: none;
  transition: all 0.6s var(--ease-out);
}

/* Seat number */
.seat-num {
  font-size: var(--font-3xl);
  font-weight: 800;
  color: var(--text-primary);
  z-index: 1;
  transition: all 0.3s var(--ease-out);
  letter-spacing: -0.02em;
}
.seat-num.dim { color: var(--text-dim); font-weight: 600; }

/* State label */
.seat-state { z-index: 1; }
.state {
  font-size: var(--font-xs);
  font-weight: 500;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  letter-spacing: 0.03em;
}
.state.checked { background: rgba(60, 184, 120, 0.18); color: var(--success); }
.state.occ { background: rgba(91, 156, 230, 0.18); color: var(--accent-light); }
.state.empty { color: var(--text-dim); }

/* Attendee name */
.seat-name {
  font-size: var(--font-sm);
  color: var(--text-secondary);
  z-index: 1;
  max-width: 80%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Self tag */
.my-tag {
  position: absolute;
  top: 10px;
  right: 12px;
  font-size: 10px;
  font-weight: 600;
  background: var(--accent);
  color: #fff;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  z-index: 2;
  letter-spacing: 0.05em;
}

/* Responsive: 2 columns on narrow screens */
@media (max-width: 600px) {
  .seat-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
  }
  .seat-card { max-height: 180px; }
  .seat-num { font-size: var(--font-2xl); }
}
</style>
