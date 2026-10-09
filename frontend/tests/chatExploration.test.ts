import { describe, expect, it } from 'vitest'
import { chatExplorationMode } from '../shared/utils/chatExploration'

describe('chatExplorationMode', () => {
  it('defaults to automatic exploration', () => {
    expect(chatExplorationMode({}, [])).toBe('auto')
  })

  it('uses current message metadata before persisted parts', () => {
    expect(chatExplorationMode(
      { explorationMode: 'force' },
      [{ type: 'data-chat-preferences', data: { exploration_mode: 'off' } }],
    )).toBe('force')
  })

  it('restores persisted exploration preference', () => {
    expect(chatExplorationMode({}, [
      { type: 'data-chat-preferences', data: { exploration_mode: 'force' } },
    ])).toBe('force')
  })
})
