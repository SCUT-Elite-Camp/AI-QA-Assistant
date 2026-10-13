import { describe, expect, it } from 'vitest'
import { developmentLoginAllowed } from '../server/utils/developmentAccess'

describe('local development login boundary', () => {
  it('requires an explicit development setting and a local connection', () => {
    expect(developmentLoginAllowed({ NODE_ENV: 'production' }, '127.0.0.1', '127.0.0.1')).toBe(false)
    expect(developmentLoginAllowed({}, 'localhost', '127.0.0.1')).toBe(false)
    expect(developmentLoginAllowed({ NODE_ENV: 'development' }, 'localhost', '127.0.0.1')).toBe(true)
    expect(developmentLoginAllowed({ ALLOW_DEV_LOGIN: 'true' }, '[::1]', '::1')).toBe(true)
  })
  it('rejects remote connections even when host headers claim localhost', () => {
    const env = { ALLOW_DEV_LOGIN: 'true' }
    expect(developmentLoginAllowed(env, 'localhost', '192.0.2.1')).toBe(false)
    expect(developmentLoginAllowed(env, 'example.com', '127.0.0.1')).toBe(false)
    expect(developmentLoginAllowed(env, 'localhost')).toBe(false)
  })
})
