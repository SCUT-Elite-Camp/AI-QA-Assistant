import { describe, expect, it, vi } from 'vitest'
import {
  AgentInternalClientError,
  callChatWithPersistentFallback,
  callInternalChat,
  isPersistentMemoryEnabled,
  shouldUsePersistentMemory
} from '../../server/utils/agentInternalClient'

const environment = {
  AGENT_BASE_URL: 'http://agent.test',
  AGENT_INTERNAL_TOKEN: 'internal-token',
  PERSISTENT_MEMORY_ENABLED: 'true'
}

function request() {
  return {
    query: 'Question',
    top_k: 5,
    stream: false,
    retrieval_mode: 'hybrid' as const,
    consecutive_no_new_docs_count: 0,
    memory_context: {
      actor: { user_id: 'user-a', authenticated: true as const },
      chat_id: 'chat-a',
      revision: 1,
      current_message_id: 'message-2',
      current_sequence: 2,
      snapshot: null,
      facts: [],
      tail: [{ id: 'message-1', sequence: 1, revision: 1, role: 'user' as const, content: 'Earlier question' }]
    }
  }
}

describe('Agent internal client', () => {
  it('sends only the token-protected internal request when persistent Memory is selected', async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      response: { trace_id: 'trace-1', status: 'success', answer: 'Answer.', message: '', citations: [] },
      memory_decision: { fact_proposals: [] }
    }), { status: 200 }))

    const response = await callInternalChat(request(), { environment, fetchFn })
    expect(response.response.answer).toBe('Answer.')
    expect(fetchFn).toHaveBeenCalledWith('http://agent.test/api/internal/chat', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Agent-Internal-Token': 'internal-token' })
    }))
  })

  it('uses the public callback exactly once only for persistent_memory_disabled', async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'persistent_memory_disabled' }), { status: 409 }))
    const callPublic = vi.fn().mockResolvedValue({ status: 'success', answer: 'Public answer' })

    await expect(callChatWithPersistentFallback({
      usePersistentMemory: true,
      internalRequest: request(),
      callPublic,
      options: { environment, fetchFn }
    })).resolves.toEqual({ status: 'success', answer: 'Public answer' })
    expect(callPublic).toHaveBeenCalledTimes(1)
  })

  it('does not downgrade other internal errors or allow anonymous persistent selection', async () => {
    const callPublic = vi.fn()
    await expect(callChatWithPersistentFallback({
      usePersistentMemory: true,
      internalRequest: request(),
      callPublic,
      options: {
        environment,
        fetchFn: vi.fn().mockResolvedValue(new Response('', { status: 500 }))
      }
    })).rejects.toMatchObject({ code: 'agent_internal_http_error' })
    expect(callPublic).not.toHaveBeenCalled()
    expect(isPersistentMemoryEnabled(environment)).toBe(true)
    expect(shouldUsePersistentMemory(false, environment)).toBe(false)
  })
})
