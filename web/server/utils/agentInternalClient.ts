import { z } from 'zod'
import { getAgentInternalToken, resolveAgentBaseUrl } from './chatAccess'
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
  environment?: Record<string, string | undefined>
  fetchFn?: typeof fetch
  signal?: AbortSignal
}

export function isPersistentMemoryEnabled (environment: Record<string, string | undefined> = process.env): boolean {
  return ['1', 'true', 'yes', 'on'].includes(environment.PERSISTENT_MEMORY_ENABLED?.trim().toLowerCase() ?? '')
}

export function shouldUsePersistentMemory (isAuthenticated: boolean, environment?: Record<string, string | undefined>): boolean {
  return isAuthenticated && isPersistentMemoryEnabled(environment)
}

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
    const response = await (options.fetchFn ?? fetch)(`${resolveAgentBaseUrl(environment)}/api/internal${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Agent-Internal-Token': token
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
    throw error
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
  usePersistentMemory: boolean
  options?: AgentInternalClientOptions
}): Promise<T | InternalChatResponse> {
  if (!input.usePersistentMemory) return input.callPublic()

  try {
    return await callInternalChat(input.internalRequest, input.options)
  } catch (error) {
    if (error instanceof AgentInternalClientError && error.code === 'persistent_memory_disabled') {
      return input.callPublic()
    }
    throw error
  }
}
