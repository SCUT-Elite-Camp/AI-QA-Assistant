import { describe, expect, it } from 'vitest'
import { canRetryMissingResponse } from '../src/utils/regeneration'

describe('failed response regeneration', () => {
  const response = { id: 'last', role: 'assistant' }
  it('allows a missing final failed response to be retried', () => {
    expect(canRetryMissingResponse({ statusCode: 404 }, 'error', response, 'last')).toBe(true)
    expect(canRetryMissingResponse({ status: 404 }, 'error', response, 'last')).toBe(true)
  })
  it.each([401, 403, 409, 500])('preserves mutation failure %s', (statusCode) => {
    expect(canRetryMissingResponse({ statusCode }, 'error', response, 'last')).toBe(false)
  })
  it('does not skip history failures for healthy or earlier messages', () => {
    expect(canRetryMissingResponse({ statusCode: 404 }, 'ready', response, 'last')).toBe(false)
    expect(canRetryMissingResponse({ statusCode: 404 }, 'error', response, 'newer')).toBe(false)
    expect(canRetryMissingResponse({ statusCode: 404 }, 'error', { id: 'last', role: 'user' }, 'last')).toBe(false)
    expect(canRetryMissingResponse(undefined, 'error', response, 'last')).toBe(false)
  })
})
