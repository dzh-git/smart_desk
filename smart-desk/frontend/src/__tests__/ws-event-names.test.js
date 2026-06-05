import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'

function readFile(relativePath) {
  return fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf-8')
}

describe('WebSocket Event Names - Migration B2', () => {
  const OLD_EVENTS = ['vote_update', 'vote_cast', 'translation_result', 'service_update']
  const NEW_EVENTS = ['vote_updated', 'translation_final', 'service_call_created', 'service_call_resolved', 'service_call_cancelled']

  const filesToCheck = [
    'components/VotingPanel.vue',
    'components/ServicePanel.vue',
    'components/TranslationPanel.vue',
    'components/SeatGrid.vue',
    'views/MeetingView.vue',
    'composables/useWebSocket.js',
  ]

  describe('Old event names must NOT be present in source files', () => {
    for (const file of filesToCheck) {
      for (const oldEvent of OLD_EVENTS) {
        it(`${file} should NOT contain '${oldEvent}'`, () => {
          const content = readFile(file)
          // Use quoted forms to avoid substring false positives
          // e.g. 'vote_updated' contains 'vote_update' as substring
          expect(content).not.toContain(`'${oldEvent}'`)
          expect(content).not.toContain(`"${oldEvent}"`)
          expect(content).not.toContain('`' + oldEvent + '`')
        })
      }
    }
  })

  describe('New event names must be present where expected', () => {
    it('VotingPanel.vue should use vote_updated', () => {
      const content = readFile('components/VotingPanel.vue')
      expect(content).toContain('vote_updated')
    })

    it('ServicePanel.vue should use service_call_created', () => {
      const content = readFile('components/ServicePanel.vue')
      expect(content).toContain('service_call_created')
      expect(content).toContain('service_call_resolved')
      expect(content).toContain('service_call_cancelled')
    })

    it('TranslationPanel.vue should use translation_final', () => {
      const content = readFile('components/TranslationPanel.vue')
      expect(content).toContain('translation_final')
    })

    it('SeatGrid.vue should use vote_updated', () => {
      const content = readFile('components/SeatGrid.vue')
      expect(content).toContain('vote_updated')
    })

    it('MeetingView.vue should not use old event names', () => {
      const content = readFile('views/MeetingView.vue')
      for (const oldEvent of OLD_EVENTS) {
        expect(content).not.toContain(`'${oldEvent}'`)
        expect(content).not.toContain(`"${oldEvent}"`)
        expect(content).not.toContain('`' + oldEvent + '`')
      }
    })

    it('useWebSocket.js should not use old event names', () => {
      const content = readFile('composables/useWebSocket.js')
      for (const oldEvent of OLD_EVENTS) {
        expect(content).not.toContain(`'${oldEvent}'`)
        expect(content).not.toContain(`"${oldEvent}"`)
        expect(content).not.toContain('`' + oldEvent + '`')
      }
    })
  })

  describe('service_update must be split into three specific events', () => {
    it('ServicePanel.vue should handle all three service_call_* events', () => {
      const content = readFile('components/ServicePanel.vue')
      expect(content).not.toContain(`'service_update'`)
      expect(content).not.toContain(`"service_update"`)
      expect(content).not.toContain('`service_update`')
      expect(content).toContain('service_call_created')
      expect(content).toContain('service_call_resolved')
      expect(content).toContain('service_call_cancelled')
    })
  })
})
