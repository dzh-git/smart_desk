import { describe, it, expect, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import ConnectionLostOverlay from '../components/ConnectionLostOverlay.vue'

// Single top-level mock for api module — needed by VotingPanel and ServicePanel tests
vi.mock('../api/index.js', () => ({
  api: {
    getActiveVote: vi.fn().mockResolvedValue(null),
    createVote: vi.fn(),
    castVote: vi.fn(),
    closeVote: vi.fn(),
    listAttendees: vi.fn().mockResolvedValue([]),
    listServiceCalls: vi.fn().mockResolvedValue([]),
    createServiceCall: vi.fn(),
  },
}))

describe('ConnectionLostOverlay', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  describe('Step 1: Overlay visibility', () => {
    it('shows overlay when connected is false', () => {
      const wrapper = mount(ConnectionLostOverlay, {
        props: { connected: false },
      })
      expect(document.body.querySelector('.connection-lost-overlay')).not.toBeNull()
      expect(document.body.querySelector('.connection-lost-card')).not.toBeNull()
      expect(document.body.querySelector('.spinner')).not.toBeNull()
      expect(document.body.textContent).toContain('Connection Lost')
      expect(document.body.textContent).toContain('Reconnecting every 3 seconds...')
    })

    it('hides overlay when connected is true', () => {
      const wrapper = mount(ConnectionLostOverlay, {
        props: { connected: true },
      })
      expect(document.body.querySelector('.connection-lost-overlay')).toBeNull()
    })

    it('reactively shows/hides overlay when connected prop changes', async () => {
      const wrapper = mount(ConnectionLostOverlay, {
        props: { connected: true },
      })
      expect(document.body.querySelector('.connection-lost-overlay')).toBeNull()

      await wrapper.setProps({ connected: false })
      expect(document.body.querySelector('.connection-lost-overlay')).not.toBeNull()

      await wrapper.setProps({ connected: true })
      expect(document.body.querySelector('.connection-lost-overlay')).toBeNull()
    })
  })
})

describe('useWebSocket - appConnected module-level ref', () => {
  describe('Step 2: appConnected is exported and reactive', () => {
    it('appConnected is exported as a ref with initial value false', async () => {
      const mod = await import('../composables/useWebSocket.js')
      expect(mod.appConnected).toBeDefined()
      expect(mod.appConnected.value).toBe(false)
    })

    it('appConnected is shared module-level singleton', async () => {
      const mod = await import('../composables/useWebSocket.js')
      const originalValue = mod.appConnected.value
      mod.appConnected.value = true
      expect(mod.appConnected.value).toBe(true)
      const mod2 = await import('../composables/useWebSocket.js')
      expect(mod2.appConnected.value).toBe(true)
      mod.appConnected.value = originalValue
    })
  })
})

describe('VotingPanel - Step 4: Block interactive operations when disconnected', () => {
  let VotingPanel
  let api

  beforeAll(async () => {
    VotingPanel = (await import('../components/VotingPanel.vue')).default
    api = (await import('../api/index.js')).api
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('injects appConnected without error', async () => {
    const appConnected = ref(false)
    const seatId = ref(1)
    const isAdmin = ref(true)

    const wrapper = mount(VotingPanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
        stubs: { BaseDialog: true },
      },
    })

    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.panel').exists()).toBe(true)
  })

  it('doCreate returns early when appConnected is false', async () => {
    const appConnected = ref(false)
    const seatId = ref(1)
    const isAdmin = ref(true)

    const wrapper = mount(VotingPanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
        stubs: { BaseDialog: true },
      },
    })

    wrapper.vm.voteForm = { title: 'Test Vote', optionsText: 'Yes\nNo' }
    await wrapper.vm.doCreate()
    expect(api.createVote).not.toHaveBeenCalled()
  })

  it('doCreate proceeds when appConnected is true', async () => {
    const appConnected = ref(true)
    const seatId = ref(1)
    const isAdmin = ref(true)

    const wrapper = mount(VotingPanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
        stubs: { BaseDialog: true },
      },
    })

    wrapper.vm.voteForm = { title: 'Test Vote', optionsText: 'Yes\nNo' }
    await wrapper.vm.doCreate()
    expect(api.createVote).toHaveBeenCalled()
  })

  // CR-007: Positive-path test for doCast when connected
  it('doCast proceeds when appConnected is true', async () => {
    const appConnected = ref(true)
    const seatId = ref(1)
    const isAdmin = ref(false)

    api.listAttendees.mockResolvedValue([{ id: 10, seat_id: 1 }])
    api.getActiveVote.mockResolvedValue(null)
    api.castVote.mockResolvedValue({})

    const wrapper = mount(VotingPanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
        stubs: { BaseDialog: true },
      },
    })

    wrapper.vm.selected = { 1: 'Yes' }
    await wrapper.vm.doCast({ id: 1, options: ['Yes', 'No'], status: 'open' })
    expect(api.listAttendees).toHaveBeenCalledWith(1)
    expect(api.castVote).toHaveBeenCalledWith(1, { attendee_id: 10, option: 'Yes' })
  })

  it('doCast returns early when appConnected is false', async () => {
    const appConnected = ref(false)
    const seatId = ref(1)
    const isAdmin = ref(false)

    api.listAttendees.mockResolvedValue([{ id: 10, seat_id: 1 }])
    api.getActiveVote.mockResolvedValue(null)

    const wrapper = mount(VotingPanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
        stubs: { BaseDialog: true },
      },
    })

    wrapper.vm.selected = { 1: 'Yes' }
    await wrapper.vm.doCast({ id: 1, options: ['Yes', 'No'], status: 'open' })
    expect(api.castVote).not.toHaveBeenCalled()
  })

  // CR-007: Positive-path test for doClose when connected
  it('doClose proceeds when appConnected is true', async () => {
    const appConnected = ref(true)
    const seatId = ref(1)
    const isAdmin = ref(true)

    api.getActiveVote.mockResolvedValue(null)
    api.closeVote.mockResolvedValue({})

    const wrapper = mount(VotingPanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
        stubs: { BaseDialog: true },
      },
    })

    await wrapper.vm.doClose({ id: 1, status: 'open' })
    expect(api.closeVote).toHaveBeenCalledWith(1)
  })

  it('doClose returns early when appConnected is false', async () => {
    const appConnected = ref(false)
    const seatId = ref(1)
    const isAdmin = ref(true)

    api.getActiveVote.mockResolvedValue(null)

    const wrapper = mount(VotingPanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
        stubs: { BaseDialog: true },
      },
    })

    await wrapper.vm.doClose({ id: 1, status: 'open' })
    expect(api.closeVote).not.toHaveBeenCalled()
  })
})

describe('ServicePanel - Step 4: Block interactive operations when disconnected', () => {
  let ServicePanel
  let api

  beforeAll(async () => {
    ServicePanel = (await import('../components/ServicePanel.vue')).default
    api = (await import('../api/index.js')).api
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('injects appConnected without error', async () => {
    const appConnected = ref(false)
    const seatId = ref(1)
    const isAdmin = ref(false)

    const wrapper = mount(ServicePanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
      },
    })

    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('.panel').exists()).toBe(true)
  })

  it('doCall returns early when appConnected is false', async () => {
    const appConnected = ref(false)
    const seatId = ref(1)
    const isAdmin = ref(false)

    api.listServiceCalls.mockResolvedValue([])

    const wrapper = mount(ServicePanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
      },
    })

    await wrapper.vm.doCall('coffee')
    expect(api.createServiceCall).not.toHaveBeenCalled()
  })

  it('doCall proceeds when appConnected is true', async () => {
    const appConnected = ref(true)
    const seatId = ref(1)
    const isAdmin = ref(false)

    api.listServiceCalls.mockResolvedValue([])

    const wrapper = mount(ServicePanel, {
      props: { meetingId: 1, wsMsg: null },
      global: {
        provide: { appConnected, seatId, isAdmin },
      },
    })

    await wrapper.vm.doCall('coffee')
    expect(api.createServiceCall).toHaveBeenCalledWith(1, { seat_id: 1, service_type: 'coffee' })
  })
})
