import { ref, readonly, onUnmounted } from 'vue'

const appConnected = ref(false)

export { appConnected }

export function useWebSocket(meetingId, seatId = 0) {
  const connected = ref(false)
  const lastMessage = ref(null)
  const messageHandler = ref(null)

  let ws = null
  let reconnectTimer = null
  let pingTimer = null
  let intentionalClose = false

  function connect() {
    // CR-011: Clear old ping interval before creating a new WebSocket.
    // In real browsers, onclose fires asynchronously, so the old interval
    // may not be cleared by the onclose handler before a new one is created.
    clearInterval(pingTimer)
    // CR-012: Clear pending reconnect timer before creating a new WebSocket.
    // Prevents race where a pending reconnect creates a second concurrent connection.
    clearTimeout(reconnectTimer)
    // CR-002: Close existing WebSocket before creating a new one
    if (ws && ws.readyState !== WebSocket.CLOSED) {
      ws.close()
    }

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${location.host}/ws/${meetingId}?seat=${seatId}`

    const newWs = new WebSocket(url)
    ws = newWs
    intentionalClose = false

    newWs.onopen = () => {
      connected.value = true
      appConnected.value = true
      // heartbeat every 15s
      pingTimer = setInterval(() => {
        if (newWs.readyState === WebSocket.OPEN) newWs.send('{"type":"ping"}')
      }, 15000)
    }

    newWs.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        lastMessage.value = msg
        if (messageHandler.value) messageHandler.value(msg)
      } catch {}
    }

    newWs.onclose = () => {
      // CR-006: Only update state if this is still the current WebSocket.
      // When connect() closes an old ws and creates a new one, the old
      // onclose fires asynchronously and must not corrupt appConnected.
      if (ws !== newWs) return
      connected.value = false
      appConnected.value = false
      clearInterval(pingTimer)
      // CR-001: Skip reconnect on intentional disconnect
      if (intentionalClose) {
        intentionalClose = false
        return
      }
      // CR-003: Guard against appConnected already being true
      reconnectTimer = setTimeout(() => {
        if (!appConnected.value) {
          connect()
        }
      }, 3000)
    }

    newWs.onerror = () => {
      // CR-009: Guard against stale WebSocket events
      if (ws !== newWs) return
      // CR-005: Set appConnected to false directly in onerror
      appConnected.value = false
      // CR-010: Also set instance-level connected to false
      connected.value = false
      newWs.close()
    }
  }

  function send(msg) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    }
  }

  function onMessage(fn) {
    messageHandler.value = fn
  }

  function disconnect() {
    // CR-001: Mark as intentional so onclose won't schedule reconnect
    intentionalClose = true
    clearTimeout(reconnectTimer)
    clearInterval(pingTimer)
    ws?.close()
  }

  onUnmounted(disconnect)

  return { connected, lastMessage, connect, send, onMessage, disconnect, appConnected: readonly(appConnected) }
}
