import { describe, it, expect } from 'vitest'
import { getSessionSecret } from '../../server/utils/session'
import {
  getAgentInternalToken,
  isChatOwnedByActor,
  requireAuthenticatedActorId,
  resolveAgentBaseUrl,
  resolveChatActor
} from '../../server/utils/chatAccess'

describe('chatAccess', () => {
  it('anonymous chats use only the server-issued session ID', () => {
    const actor = resolveChatActor({ id: 'anonymous-session-a', data: {} })

    expect(actor).toEqual({ userId: 'anonymous-session-a', isAuthenticated: false })
    expect(isChatOwnedByActor('anonymous-session-a', actor!)).toBe(true)
    expect(isChatOwnedByActor('anonymous-session-b', actor!)).toBe(false)
  })

  it('signed-in actor cannot be replaced by a client-supplied identity', () => {
    const actor = resolveChatActor({
      id: 'anonymous-session-a',
      data: { user: { id: 'user-a' } }
    })

    expect(actor).toEqual({ userId: 'user-a', isAuthenticated: true })
    expect(isChatOwnedByActor('user-b', actor!)).toBe(false)
    expect(requireAuthenticatedActorId({ id: 'anonymous-session-a', data: { user: { id: 'user-a' } } })).toBe('user-a')
  })

  it('Fact actor requires a signed-in user', () => {
    expect(() => requireAuthenticatedActorId({ id: 'anonymous-session-a', data: {} })).toThrow()
  })

  it('production configuration does not fall back to session or Agent defaults', () => {
    expect(() => getSessionSecret({ NODE_ENV: 'production' })).toThrow(/SESSION_SECRET/)
    expect(() => resolveAgentBaseUrl({ NODE_ENV: 'production' })).toThrow(/AGENT_BASE_URL/)
    expect(getSessionSecret({ NODE_ENV: 'development' })).toBe('development_only_session_secret_key_qa_assistant_2026')
    expect(resolveAgentBaseUrl({ NODE_ENV: 'development' })).toBe('http://127.0.0.1:8000')
  })

  it('Agent token remains server configuration and is never synthesized', () => {
    expect(getAgentInternalToken({})).toBeUndefined()
    expect(getAgentInternalToken({ AGENT_INTERNAL_TOKEN: ' token-value ' })).toBe('token-value')
  })
})
