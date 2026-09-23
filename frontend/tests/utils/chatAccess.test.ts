import { describe, expect, it } from 'vitest'

describe('chat access boundary', () => {
  it('uses the authenticated server identity instead of an anonymous session', async () => {
    const { resolveChatActor } = await import('../../server/utils/chatAccess')

    expect(resolveChatActor({
      id: 'anonymous-session-a',
      data: { user: { id: 'user-a' } }
    })).toEqual({ userId: 'user-a', isAuthenticated: true })
  })

  it('keeps anonymous chats bound to their server-issued session', async () => {
    const { isChatOwnedByActor, resolveChatActor } = await import('../../server/utils/chatAccess')
    const actor = resolveChatActor({ id: 'anonymous-session-a', data: {} })

    expect(actor).toEqual({ userId: 'anonymous-session-a', isAuthenticated: false })
    expect(isChatOwnedByActor('anonymous-session-b', actor!)).toBe(false)
  })

  it('requires a signed-in actor for Fact operations', async () => {
    const { requireAuthenticatedActorId } = await import('../../server/utils/chatAccess')

    expect(() => requireAuthenticatedActorId({ id: 'anonymous-session-a', data: {} })).toThrow(/Authentication required/)
  })
})
