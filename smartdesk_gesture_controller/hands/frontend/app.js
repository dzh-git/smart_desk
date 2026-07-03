(function () {
  'use strict';

  const WS_URL = 'ws://' + location.host;
  const RECONNECT_INTERVAL_MS = 1200;
  const PAGE_GLOW_MS = 800;
  const HAND_LOSS_TIMEOUT = 1.0; // should match backend default, only used as fallback

  const card = document.getElementById('card');
  const cameraBadge = document.getElementById('camera-badge');
  const handBadge = document.getElementById('hand-badge');
  const statusBadge = document.getElementById('status-badge');

  let socket = null;
  let reconnectTimer = null;
  let pageGlowTimer = null;
  let forcedGlow = null; // 'next' | 'previous' | null

  // ---------- badge helpers ----------

  function setBadge(element, text, color) {
    element.textContent = text;
    element.className = 'badge badge-' + color;
  }

  function setCardGlow(enabled) {
    if (enabled) {
      card.classList.add('glow');
    } else {
      card.classList.remove('glow');
    }
  }

  // ---------- state derivation ----------

  function deriveCamera(snapshot) {
    return snapshot.camera_ok
      ? { text: 'Online', color: 'green' }
      : { text: 'Offline', color: 'rose' };
  }

  function deriveHand(snapshot) {
    if (!snapshot.camera_ok) {
      return { text: 'Unavailable', color: 'muted' };
    }
    if (snapshot.hand_present || (snapshot.gesture && snapshot.gesture !== 'none')) {
      return { text: 'Detected', color: 'green' };
    }
    const lost = snapshot.hand_lost_duration || 0;
    if (lost > HAND_LOSS_TIMEOUT) {
      return { text: 'Lost', color: 'rose' };
    }
    return { text: 'Searching', color: 'amber' };
  }

  function isRecognizing(snapshot) {
    const phase = snapshot.intent_phase || '';
    return phase.indexOf('attempt:') !== -1 ||
           phase.indexOf('session_candidate:') !== -1 ||
           phase.indexOf('hold:') !== -1;
  }

  function isDrawing(snapshot) {
    const action = snapshot.action || '';
    const phase = snapshot.intent_phase || '';
    return action.indexOf('pen_draw') !== -1 || phase.indexOf('session:pen') !== -1;
  }

  function deriveStatus(snapshot, hand, now) {
    if (snapshot.paused || snapshot.control_enabled === false) {
      return { text: 'Paused', color: 'amber', glow: false };
    }
    if (!snapshot.camera_ok) {
      return { text: 'Camera Offline', color: 'rose', glow: false };
    }
    if (hand.text === 'Lost') {
      return { text: 'Hand Lost', color: 'rose', glow: false };
    }
    if (hand.text === 'Searching') {
      return { text: 'Show Your Hand', color: 'amber', glow: false };
    }
    if (snapshot.mode === 'standby') {
      return { text: 'Standby', color: 'muted', glow: false };
    }
    if (snapshot.mode === 'presentation_pen') {
      return { text: 'Pen Mode', color: 'cyan', glow: isDrawing(snapshot) };
    }
    if (snapshot.mode === 'solidworks') {
      return { text: 'SolidWorks', color: 'cyan', glow: false };
    }

    if (forcedGlow === 'next') {
      return { text: 'Next Slide', color: 'cyan', glow: true };
    }
    if (forcedGlow === 'previous') {
      return { text: 'Previous Slide', color: 'cyan', glow: true };
    }

    const cooldownUntil = snapshot.cooldown_until || 0;
    if (cooldownUntil > now) {
      return { text: 'Cooling Down', color: 'muted', glow: false };
    }

    if (isRecognizing(snapshot)) {
      return { text: 'Recognizing', color: 'cyan', glow: true };
    }

    if (snapshot.mode === 'presentation') {
      return { text: 'Ready to Flip', color: 'green', glow: false };
    }

    return { text: 'Standby', color: 'muted', glow: false };
  }

  // ---------- page-turn glow ----------

  function triggerPageTurnGlow(direction) {
    forcedGlow = direction;
    if (pageGlowTimer) {
      clearTimeout(pageGlowTimer);
    }
    pageGlowTimer = setTimeout(() => {
      forcedGlow = null;
      pageGlowTimer = null;
      // The next incoming message will re-render without forced glow.
    }, PAGE_GLOW_MS);
  }

  function checkPageTurn(snapshot) {
    const action = snapshot.action || '';
    const gesture = snapshot.gesture || '';
    // Prefer the action / note text from the backend if available.
    if (action.indexOf('page_swipe_right') !== -1 || action.indexOf('Next') !== -1) {
      triggerPageTurnGlow('next');
      return;
    }
    if (action.indexOf('page_swipe_left') !== -1 || action.indexOf('Previous') !== -1) {
      triggerPageTurnGlow('previous');
      return;
    }
    // Legacy fallback: gesture name sometimes carries direction.
    if (gesture.indexOf('page_swipe_right') !== -1) {
      triggerPageTurnGlow('next');
    } else if (gesture.indexOf('page_swipe_left') !== -1) {
      triggerPageTurnGlow('previous');
    }
  }

  // ---------- render ----------

  function render(snapshot) {
    const now = Date.now() / 1000;

    const camera = deriveCamera(snapshot);
    setBadge(cameraBadge, camera.text, camera.color);

    const hand = deriveHand(snapshot);
    setBadge(handBadge, hand.text, hand.color);

    checkPageTurn(snapshot);

    const status = deriveStatus(snapshot, hand, now);
    setBadge(statusBadge, status.text, status.color);
    setCardGlow(status.glow);
  }

  function renderDisconnected() {
    setBadge(cameraBadge, 'Offline', 'rose');
    setBadge(handBadge, 'Unavailable', 'muted');
    setBadge(statusBadge, 'Camera Offline', 'rose');
    setCardGlow(false);
  }

  // ---------- websocket ----------

  function connect() {
    if (socket) {
      try { socket.close(); } catch (e) { /* ignore */ }
    }

    try {
      socket = new WebSocket(WS_URL);
    } catch (err) {
      renderDisconnected();
      scheduleReconnect();
      return;
    }

    socket.onopen = () => {
      // Server sends an immediate snapshot on connection.
    };

    socket.onmessage = (event) => {
      try {
        const snapshot = JSON.parse(event.data);
        render(snapshot);
      } catch (err) {
        // Ignore malformed payloads; keep previous state.
      }
    };

    socket.onclose = () => {
      socket = null;
      renderDisconnected();
      scheduleReconnect();
    };

    socket.onerror = () => {
      // onclose will fire next and trigger reconnect.
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, RECONNECT_INTERVAL_MS);
  }

  // ---------- init ----------

  renderDisconnected();
  connect();
})();
