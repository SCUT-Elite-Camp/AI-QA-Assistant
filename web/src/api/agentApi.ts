import type { UIMessage } from 'ai'
import { getErrorMessage } from '../mock/errorMap'

const DEFAULT_API_BASE_URL = 'http://localhost:8080'
const DEFAULT_CHAT_PATH = '/api/v1/chat'
const DEFAULT_SESSION_ID = 'local-session-001'

export interface BffCitation {
  title: string
  source_url?: string
  snippet?: string
}

export interface BffChatResponse {
  trace_id: string
  status: string
  answer: string
  citations: BffCitation[]
}

export interface SendChatOptions {
  sessionId?: string
  stream?: boolean
}

function createMessageId(prefix = 'msg'): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 8)}`
}

function getApiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/+$/u, '')
}

function getChatPath(): string {
  const path = import.meta.env.VITE_CHAT_PATH || DEFAULT_CHAT_PATH
  return path.startsWith('/') ? path : `/${path}`
}

export function getChatEndpoint(): string {
  return `${getApiBaseUrl()}${getChatPath()}`
}

export function createUserMessage(text: string): UIMessage {
  return {
    id: createMessageId('user'),
    role: 'user',
    parts: [{ type: 'text' as const, text }],
  } as unknown as UIMessage
}

export function adaptBffResponseToMessage(response: BffChatResponse): UIMessage {
  const citationText = response.citations.length
    ? `\n\n引用来源：\n${response.citations.map((citation, index) => {
        const label = citation.title || `Citation ${index + 1}`
        const source = citation.source_url ? `[${label}](${citation.source_url})` : label
        const snippet = citation.snippet ? `\n  ${citation.snippet}` : ''
        return `${index + 1}. ${source}${snippet}`
      }).join('\n')}`
    : ''

  return {
    id: createMessageId('assistant'),
    role: 'assistant',
    parts: [{
      type: 'text' as const,
      text: `${response.answer}\n\ntrace_id: ${response.trace_id}${citationText}`,
    }],
  } as unknown as UIMessage
}

export async function sendChatMessage(query: string, options: SendChatOptions = {}): Promise<UIMessage> {
  const endpoint = getChatEndpoint()

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query,
        session_id: options.sessionId ?? DEFAULT_SESSION_ID,
        stream: options.stream ?? false,
      }),
    })

    if (!response.ok) {
      const error = new Error(getErrorMessage(response.status === 400 ? 'invalid_query' : 'unknown_error')) as Error & { status?: string }
      error.status = response.status === 400 ? 'invalid_query' : 'unknown_error'
      throw error
    }

    const data = await response.json() as BffChatResponse
    return adaptBffResponseToMessage(data)
  } catch (error) {
    if (error instanceof Error && 'status' in error) {
      throw error
    }

    const networkError = new Error(getErrorMessage('network_error')) as Error & { status?: string }
    networkError.status = 'network_error'
    throw networkError
  }
}
