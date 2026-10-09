import { describe, expect, it } from 'vitest'
import { isSessionFactEnabled } from '../../server/utils/sessionFactGate'

describe('SESSION_FACT_ENABLED gate', () => {
  it('defaults closed and fails closed for non-boolean values', () => {
    expect(isSessionFactEnabled({})).toBe(false)
    expect(isSessionFactEnabled({ SESSION_FACT_ENABLED: 'sometimes' })).toBe(false)
    expect(isSessionFactEnabled({ SESSION_FACT_ENABLED: '0' })).toBe(false)
  })

  it.each(['1', 'true', 'TRUE', ' yes ', 'on'])('opens only for explicit true values: %s', (value) => {
    expect(isSessionFactEnabled({ SESSION_FACT_ENABLED: value })).toBe(true)
  })
})
