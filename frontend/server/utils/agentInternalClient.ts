import { z } from 'zod'
import { getAgentInternalToken, resolveAgentBaseUrl } from './agentConfig'
import { shouldUsePersistentMemory } from './memoryFeatureFlags'
import {
  compactionPlanRequestSchema,
  compactionPlanResponseSchema,
  internalChatRequestSchema,
  internalChatResponseSchema,
  resetShortWindowRequestSchema,
  resetShortWindowResponseSchema,
  type CompactionPlanRequest,
  type InternalChatRequest,
  type InternalChatResponse
} from './memoryContract'

const INTERNAL_TIMEOUT_MS = 5_000

export type AgentInternalErrorCode = 'persistent_memory_disabled' | 'agent_internal_configuration' | 'agent_internal_http_error' | 'agent_internal_invalid_response' | 'agent_internal_timeout'
export type MemoryFallbackReason = 'agent_disabled' | 'internal_error'

export class AgentInternalClientError extends Error {
  constructor (
    readonly code: AgentInternalErrorCode,
    message: string,
    readonly status?: number
  ) {
    super(message)
    this.name = 'AgentInternalClientError'
  }
}

export interface AgentInternalClientOptions {
  actorUserId?: string
  environment?: Record<string, string | undefined>
  fetchFn?: typeof fetch
  signal?: AbortSignal
}

/**
 * The wrapper is constructed only by this server-side client. Callers must
 * use `source`, rather than inspecting fields in an Agent response, when a
 * side effect is reserved for the token-protected internal endpoint.
 */
export type PersistentChatCallResult<T> =
  | { source: 'internal', value: InternalChatResponse }
  | { source: 'public', value: T }

export { shouldUsePersistentMemory }

async function postInternal<TRequest, TResponse> (
  path: string,
  request: TRequest,
  requestSchema: z.ZodType<TRequest>,
  responseSchema: z.ZodType<TResponse>,
  options: AgentInternalClientOptions = {}
): Promise<TResponse> {
  const environment = options.environment ?? process.env
  const token = getAgentInternalToken(environment)
  if (!token) {
    throw new AgentInternalClientError('agent_internal_configuration', 'AGENT_INTERNAL_TOKEN is required for persistent Memory')
  }

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), INTERNAL_TIMEOUT_MS)
  const abortFromCaller = () => controller.abort()
  options.signal?.addEventListener('abort', abortFromCaller, { once: true })

  try {
    const envelope = request as { actor?: { user_id: string }, memory_context?: { actor: { user_id: string } } }
    const actorUserId = envelope.actor?.user_id || envelope.memory_context?.actor.user_id
    if (!actorUserId && path !== '/memory/reset-short-window') throw new AgentInternalClientError('agent_internal_configuration', 'Trusted actor is required')
    const response = await (options.fetchFn ?? fetch)(`${resolveAgentBaseUrl(environment)}/api/internal${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${environment.AGENT_API_KEY || ''}`,
        'X-Agent-Internal-Token': token,
        'X-User-ID': actorUserId || options.actorUserId || ''
      },
      body: JSON.stringify(requestSchema.parse(request)),
      signal: controller.signal
    })

    if (response.status === 409) {
      const body = await response.json().catch(() => undefined)
      if (body?.code === 'persistent_memory_disabled') {
        throw new AgentInternalClientError('persistent_memory_disabled', 'Agent persistent Memory is disabled', 409)
      }
    }

    if (!response.ok) {
      throw new AgentInternalClientError('agent_internal_http_error', 'Agent internal request failed', response.status)
    }

    try {
      return responseSchema.parse(await response.json())
    } catch {
      throw new AgentInternalClientError('agent_internal_invalid_response', 'Agent internal response violated the contract')
    }
  } catch (error) {
    if (error instanceof AgentInternalClientError) throw error
    if (controller.signal.aborted) {
      throw new AgentInternalClientError('agent_internal_timeout', 'Agent internal request timed out')
    }
    throw new AgentInternalClientError('agent_internal_http_error', 'Agent internal request failed')
  } finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abortFromCaller)
  }
}

export function callInternalChat (request: InternalChatRequest, options?: AgentInternalClientOptions): Promise<InternalChatResponse> {
  return postInternal('/chat', request, internalChatRequestSchema, internalChatResponseSchema, options)
}

export function requestCompactionPlan (request: CompactionPlanRequest, options?: AgentInternalClientOptions) {
  return postInternal('/memory/compaction-plan', request, compactionPlanRequestSchema, compactionPlanResponseSchema, options)
}

export function resetShortWindow (chatId: string, options?: AgentInternalClientOptions) {
  const request = { chat_id: chatId }
  return postInternal('/memory/reset-short-window', request, resetShortWindowRequestSchema, resetShortWindowResponseSchema, options)
}

export async function callChatWithPersistentFallback<T> (input: {
  internalRequest: InternalChatRequest
  callPublic: () => Promise<T>
  onFallback?: (reason: MemoryFallbackReason) => void
  usePersistentMemory: boolean
  options?: AgentInternalClientOptions
}): Promise<PersistentChatCallResult<T>> {
  if (!input.usePersistentMemory) {
    return { source: 'public', value: await input.callPublic() }
  }

  try {
    return { source: 'internal', value: await callInternalChat(input.internalRequest, input.options) }
  } catch (error) {
    if (error instanceof AgentInternalClientError && error.code !== 'agent_internal_configuration') {
      input.onFallback?.(
        error.code === 'persistent_memory_disabled' ? 'agent_disabled' : 'internal_error'
      )
      return { source: 'public', value: await input.callPublic() }
    }
    throw error
  }
}
