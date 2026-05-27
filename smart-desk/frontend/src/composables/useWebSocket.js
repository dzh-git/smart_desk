import { ref, onUnmounted } from 'vue'

export function useWebSocket(meetingId, seatId = 0) {
  const connected = ref(false)
  const lastMessage = ref(null)
  const messageHandler = ref(null)

  let ws = null
  let reconnectTimer = null
  let pingTimer = null

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${location.host}/ws/${meetingId}?seat=${seatId}`

    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
      // heartbeat every 15s
      pingTimer = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) ws.send('{"type":"ping"}')
      }, 15000)
    }

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        lastMessage.value = msg
        if (messageHandler.value) messageHandler.value(msg)
      } catch {}
    }

    ws.onclose = () => {
      connected.value = false
      clearInterval(pingTimer)
      // auto-reconnect after 3s
      reconnectTimer = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws?.close()
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
    clearTimeout(reconnectTimer)
    clearInterval(pingTimer)
    ws?.close()
  }

  onUnmounted(disconnect)

  return { connected, lastMessage, connect, send, onMessage, disconnect }
}
