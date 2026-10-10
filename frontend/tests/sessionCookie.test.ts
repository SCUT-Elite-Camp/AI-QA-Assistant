import { describe, expect, it } from 'vitest'
import { getSessionCookieSecure } from '../server/utils/session'

describe('shared session and CSRF cookie transport policy', () => {
  it('defaults to secure in production and supports explicit loopback HTTP verification', () => {
    expect(getSessionCookieSecure({ NODE_ENV: 'production' })).toBe(true)
    expect(getSessionCookieSecure({ NODE_ENV: 'production', SESSION_COOKIE_SECURE: 'false' })).toBe(false)
    expect(getSessionCookieSecure({ NODE_ENV: 'development' })).toBe(false)
    expect(getSessionCookieSecure({ NODE_ENV: 'development', SESSION_COOKIE_SECURE: 'true' })).toBe(true)
  })
  it('rejects an ambiguous opt-out instead of silently disabling protection', () => {
    expect(() => getSessionCookieSecure({ SESSION_COOKIE_SECURE: 'no' })).toThrow('Invalid SESSION_COOKIE_SECURE')
  })
})
