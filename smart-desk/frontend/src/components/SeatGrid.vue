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
      @click="onSeatClick(seat)"
    >
      <!-- LED glow ring -->
      <div
        class="led-ring"
        :style="ledStyle(seat)"
      ></div>

      <!-- Seat number -->
      <div class="seat-num">{{ seat.id }}</div>

      <!-- State label -->
      <div class="seat-state">
        <span v-if="seat.checkedIn" class="state checked">已签到</span>
        <span v-else-if="seat.occupied" class="state occ">有人</span>
        <span v-else class="state empty">空</span>
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
  return { id: i + 1, occupied: false, checkedIn: false, name: '', ledPattern: 'breathe', ledColor: [255, 200, 150] }
}
const seats = reactive(Array.from({ length: 8 }, (_, i) => makeSeat(i)))

const showCheckin = ref(false)
const activeSeat = ref(1)
const wsRef = ref(null)

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
          s.ledColor = [80, 140, 255]
        }
      }
    }
  } catch {}
})

function ledStyle(seat) {
  const [r, g, b] = seat.ledColor
  const opacity = seat.checkedIn ? 0.6 : seat.occupied ? 0.4 : 0.15
  const anim = seat.occupied && !seat.checkedIn ? 'glow-breathe 2s ease-in-out infinite' : 'none'
  return {
    boxShadow: `0 0 20px rgba(${r},${g},${b},${opacity}), 0 0 60px rgba(${r},${g},${b},${opacity * 0.5})`,
    borderColor: `rgba(${r},${g},${b},${opacity * 2})`,
    animation: anim,
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

// WS: update seat states from server
watch(() => props.wsMsg, (msg) => {
  if (!msg) return
  const p = msg.payload || {}
  const sid = p.seat_id

  if (msg.type === 'seat_occupied' && sid) {
    const s = seats.find(s => s.id === sid)
    if (s) { s.occupied = true; s.ledPattern = 'wave'; s.ledColor = [80, 140, 255] }
  }
  if (msg.type === 'seat_vacant' && sid) {
    const s = seats.find(s => s.id === sid)
    if (s) { s.occupied = false; s.checkedIn = false; s.name = ''; s.ledPattern = 'breathe'; s.ledColor = [255, 200, 150] }
  }
  if (msg.type === 'check_in' && sid) {
    const s = seats.find(s => s.id === sid)
    if (s) { s.checkedIn = true; s.ledPattern = 'solid'; s.ledColor = [255, 220, 180] }
  }
  if (msg.type === 'vote_cast' && p.vote_id) {
    // Flash gold on all seats during vote
    seats.forEach(s => { s.ledColor = [201, 168, 76]; s.ledPattern = 'solid' })
    setTimeout(() => {
      seats.forEach(s => {
        if (s.checkedIn) s.ledColor = [255, 220, 180]
        else if (s.occupied) s.ledColor = [80, 140, 255]
        else s.ledColor = [255, 200, 150]
      })
    }, 2000)
  }
})
</script>

<style scoped>
.seat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  max-width: 900px;
  margin: 0 auto;
}

.seat-card {
  position: relative;
  aspect-ratio: 1;
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  border: 2px solid rgba(255,255,255,0.06);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  transition: all 0.4s ease;
  overflow: hidden;
}
.seat-card:hover {
  background: var(--bg-card-hover);
  transform: translateY(-2px);
}
.seat-card.self {
  border-color: rgba(74,144,217,0.3);
}

.led-ring {
  position: absolute;
  inset: 8px;
  border-radius: var(--radius-lg);
  border: 2px solid transparent;
  pointer-events: none;
  transition: all 0.6s ease;
}

.seat-num {
  font-size: 2.4rem;
  font-weight: 700;
  color: var(--text-primary);
  z-index: 1;
}

.seat-state {
  z-index: 1;
}
.state {
  font-size: var(--font-sm);
  padding: 2px 10px;
  border-radius: 12px;
}
.state.checked { background: rgba(60,184,120,0.2); color: var(--success); }
.state.occ { background: rgba(74,144,217,0.2); color: var(--accent); }
.state.empty { color: var(--text-dim); }

.seat-name {
  font-size: var(--font-sm);
  color: var(--text-secondary);
  z-index: 1;
}

.my-tag {
  position: absolute;
  top: 10px;
  right: 12px;
  font-size: 11px;
  background: var(--accent);
  color: #fff;
  padding: 1px 8px;
  border-radius: 10px;
  z-index: 2;
}
</style>
