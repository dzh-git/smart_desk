import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'

const STORAGE_KEY = 'smartdesk_seat'
const seatId = ref(1)

export function useSeat() {
  const route = useRoute()

  function resolve() {
    const fromUrl = Number(route.query.seat)
    if (fromUrl >= 1 && fromUrl <= 8) return fromUrl
    const stored = Number(localStorage.getItem(STORAGE_KEY))
    if (stored >= 1 && stored <= 8) return stored
    return 1
  }

  seatId.value = resolve()

  watch(() => route.query.seat, (val) => {
    const n = Number(val)
    if (n >= 1 && n <= 8) {
      seatId.value = n
      localStorage.setItem(STORAGE_KEY, String(n))
    }
  })

  // No ?seat param = central console = admin
  const isAdmin = computed(() => !route.query.seat)

  return { seatId, isAdmin }
}
