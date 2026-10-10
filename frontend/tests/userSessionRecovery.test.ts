import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('ofetch', () => ({ $fetch: mocks.fetch }))
vi.mock('@vueuse/core', () => ({ createSharedComposable: (factory: unknown) => factory }))
vi.mock('../src/composables/useCsrf', () => ({ useCsrf: () => ({ csrf: () => 'test-csrf', headerName: 'x-csrf-token' }) }))

beforeEach(() => { vi.resetModules(); mocks.fetch.mockReset() })

describe('session recovery before private conversation loading', () => {
  it('shares concurrent recovery and resolves only after the authenticated session is read', async () => {
    let release!: (value: object) => void
    mocks.fetch.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
      .mockResolvedValueOnce({ success: true, user: { id: 'dev-user' } })
      .mockResolvedValueOnce({ user: { id: 'dev-user' } })
    const { useUserSession } = await import('../src/composables/useUserSession')
    const state = useUserSession()
    const first = state.fetchSession()
    const second = state.fetchSession()
    expect(second).toBe(first)
    expect(mocks.fetch).toHaveBeenCalledTimes(1)
    release({})
    expect((await first)?.user?.id).toBe('dev-user')
    expect(state.loggedIn.value).toBe(true)
    expect(mocks.fetch.mock.calls.map(call => call[0])).toEqual(['/api/session', '/api/auth/dev-login', '/api/session'])
  })

  it('allows a fresh recovery after a failed login without fabricating authentication', async () => {
    mocks.fetch.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('disabled'))
    const { useUserSession } = await import('../src/composables/useUserSession')
    const state = useUserSession()
    await state.fetchSession()
    expect(state.loggedIn.value).toBe(false)
    mocks.fetch.mockResolvedValueOnce({ user: { id: 'owner' } })
    await state.fetchSession()
    expect(state.user.value?.id).toBe('owner')
    expect(mocks.fetch).toHaveBeenCalledTimes(3)
  })
})
