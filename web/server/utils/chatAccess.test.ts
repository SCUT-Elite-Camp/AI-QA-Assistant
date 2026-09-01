import assert from 'node:assert/strict'
import test from 'node:test'
import { getSessionSecret } from './session'
import {
  getAgentInternalToken,
  isChatOwnedByActor,
  requireAuthenticatedActorId,
  resolveAgentBaseUrl,
  resolveChatActor
} from './chatAccess'

test('anonymous chats use only the server-issued session ID', () => {
  const actor = resolveChatActor({ id: 'anonymous-session-a', data: {} })

  assert.deepEqual(actor, { userId: 'anonymous-session-a', isAuthenticated: false })
  assert.equal(isChatOwnedByActor('anonymous-session-a', actor!), true)
  assert.equal(isChatOwnedByActor('anonymous-session-b', actor!), false)
})

test('signed-in actor cannot be replaced by a client-supplied identity', () => {
  const actor = resolveChatActor({
    id: 'anonymous-session-a',
    data: { user: { id: 'user-a' } }
  })

  assert.deepEqual(actor, { userId: 'user-a', isAuthenticated: true })
  assert.equal(isChatOwnedByActor('user-b', actor!), false)
  assert.equal(requireAuthenticatedActorId({ id: 'anonymous-session-a', data: { user: { id: 'user-a' } } }), 'user-a')
})

test('Fact actor requires a signed-in user', () => {
  assert.throws(
    () => requireAuthenticatedActorId({ id: 'anonymous-session-a', data: {} }),
    (error: any) => error?.statusCode === 401
  )
})

test('production configuration does not fall back to session or Agent defaults', () => {
  assert.throws(() => getSessionSecret({ NODE_ENV: 'production' }), /SESSION_SECRET/)
  assert.throws(() => resolveAgentBaseUrl({ NODE_ENV: 'production' }), /AGENT_BASE_URL/)
  assert.equal(getSessionSecret({ NODE_ENV: 'development' }), 'development_only_session_secret_key_qa_assistant_2026')
  assert.equal(resolveAgentBaseUrl({ NODE_ENV: 'development' }), 'http://127.0.0.1:8000')
})

test('Agent token remains server configuration and is never synthesized', () => {
  assert.equal(getAgentInternalToken({}), undefined)
  assert.equal(getAgentInternalToken({ AGENT_INTERNAL_TOKEN: ' token-value ' }), 'token-value')
})
