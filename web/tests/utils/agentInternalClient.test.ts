import { readFileSync } from 'node:fs'
import { describe, expect, it, vi } from 'vitest'
import {
  AgentInternalClientError,
  callChatWithPersistentFallback,
  callInternalChat,
  isPersistentMemoryEnabled,
  shouldUsePersistentMemory
} from '../../server/utils/agentInternalClient'
import {
  internalChatRequestSchema,
  internalChatResponseSchema
} from '../../server/utils/memoryContract'

const environment = {
  AGENT_BASE_URL: 'http://agent.test',
  AGENT_INTERNAL_TOKEN: 'internal-token',
  PERSISTENT_MEMORY_ENABLED: 'true'
}

function readFixture (name: string): unknown {
  return JSON.parse(readFileSync(new URL(`../../../docs/memory-context-plan/evidence/fixtures/${name}`, import.meta.url), 'utf8'))
}

function request() {
  return internalChatRequestSchema.parse(readFixture('internal-chat-request.json'))
}

describe('Agent internal client', () => {
  it('sends only the token-protected internal request when persistent Memory is selected', async () => {
    const responseFixture = internalChatResponseSchema.parse(readFixture('internal-chat-response.json'))
    const fetchFn = vi.fn().mockResolvedValue(new Response(JSON.stringify(responseFixture), { status: 200 }))

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
    })).resolves.toEqual({
      source: 'public',
      value: { status: 'success', answer: 'Public answer' }
    })
    expect(callPublic).toHaveBeenCalledTimes(1)
  })

  it('wraps a successful token-protected response with the internal provenance marker', async () => {
    const responseFixture = internalChatResponseSchema.parse(readFixture('internal-chat-response.json'))
    const fetchFn = vi.fn().mockResolvedValue(new Response(JSON.stringify(responseFixture), { status: 200 }))

    await expect(callChatWithPersistentFallback({
      usePersistentMemory: true,
      internalRequest: request(),
      callPublic: vi.fn(),
      options: { environment, fetchFn }
    })).resolves.toMatchObject({ source: 'internal', value: { response: { answer: 'Answer.' } } })
  })

  it('uses the public callback exactly once for a safe internal HTTP downgrade', async () => {
    const callPublic = vi.fn()
    const onFallback = vi.fn()
    callPublic.mockResolvedValue({ status: 'success', answer: 'Public answer' })
    await expect(callChatWithPersistentFallback({
      usePersistentMemory: true,
      internalRequest: request(),
      callPublic,
      onFallback,
      options: {
        environment,
        fetchFn: vi.fn().mockResolvedValue(new Response('', { status: 500 }))
      }
    })).resolves.toEqual({
      source: 'public',
      value: { status: 'success', answer: 'Public answer' }
    })
    expect(callPublic).toHaveBeenCalledTimes(1)
    expect(onFallback).toHaveBeenCalledWith('internal_error')
    expect(isPersistentMemoryEnabled(environment)).toBe(true)
    expect(shouldUsePersistentMemory(false, environment)).toBe(false)
  })

  it('keeps missing internal credentials fail-closed instead of calling public chat', async () => {
    const callPublic = vi.fn()
    await expect(callChatWithPersistentFallback({
      usePersistentMemory: true,
      internalRequest: request(),
      callPublic,
      options: { environment: { AGENT_BASE_URL: 'http://agent.test' } }
    })).rejects.toMatchObject({ code: 'agent_internal_configuration' })
    expect(callPublic).not.toHaveBeenCalled()
  })
})
