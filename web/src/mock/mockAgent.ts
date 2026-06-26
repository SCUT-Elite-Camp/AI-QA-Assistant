import type { UIMessage } from 'ai'
import { getErrorMessage } from './errorMap'

const MOCK_LATENCY_MS = 300
const STREAM_CHUNK_DELAY_MS = 120

const NORMAL_ANSWER =
  'This is a response from the Mock Agent. The Web Layer MVP has been upgraded to a full-stack TypeScript architecture, integrating AI SDK streaming chat, Nuxt UI component library, Nitro backend, and Drizzle ORM persistence. Currently running in Mock mode - try different keywords to test various scenarios.'

const STREAM_ANSWER =
  'This is a streaming response from the Mock Agent. The frontend receives content in chunks and appends them to the assistant message. Loading ends after all chunks are returned. Currently simulating streaming with the TypeScript full-stack architecture.'

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function createTraceId(): string {
  return `mock-trace-${Date.now().toString(36)}-${Math.random()
    .toString(16)
    .slice(2, 8)}`
}

function createMessageId(): string {
  return `msg-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 8)}`
}

function splitAnswer(answer: string): string[] {
  const chunks: string[] = []
  let buffer = ''

  for (const char of answer) {
    buffer += char

    if (/[,.!?:;\s-]/u.test(char) || buffer.length >= 8) {
      chunks.push(buffer)
      buffer = ''
    }
  }

  if (buffer) {
    chunks.push(buffer)
  }

  return chunks
}

function getQuery(payload?: { query?: string }): string {
  return String(payload?.query ?? '')
}

export function createMockUserMessage(text: string): UIMessage {
  return {
    id: createMessageId(),
    role: 'user',
    parts: [{ type: 'text' as const, text }],
  } as unknown as UIMessage
}

export function createMockAssistantMessage(): UIMessage {
  return {
    id: createMessageId(),
    role: 'assistant',
    parts: [],
  } as unknown as UIMessage
}

export function createNormalResponse(query: string): UIMessage {
  const isNoLink = query.includes('no-link')
  const sourceUrl = isNoLink ? '' : 'https://example.com/doc'

  return {
    id: createMessageId(),
    role: 'assistant',
    parts: [
      { type: 'text' as const, text: NORMAL_ANSWER },
      {
        type: 'tool-invocation' as const,
        toolInvocation: {
          state: 'result' as const,
          toolCallId: createMessageId(),
          toolName: 'web_search',
          args: { query },
          result: {
            sources: isNoLink ? [] : [{
              url: sourceUrl,
              title: 'Q1 Web Layer MVP Docs',
            }],
          },
        },
      },
    ],
  } as unknown as UIMessage
}

export function createBusinessErrorResponse(status: string): UIMessage {
  return {
    id: createMessageId(),
    role: 'assistant',
    parts: [{ type: 'text' as const, text: getErrorMessage(status) }],
  } as unknown as UIMessage
}

// Non-streaming mock: returns UIMessage
export async function mockSendChatMessage(payload?: { query?: string }): Promise<UIMessage> {
  const query = getQuery(payload)

  await delay(MOCK_LATENCY_MS)

  if (query.includes('network error')) {
    const error = new Error(getErrorMessage('network_error')) as Error & { status: string; trace_id: string }
    error.status = 'network_error'
    error.trace_id = createTraceId()
    throw error
  }

  if (query.includes('timeout')) {
    const error = new Error(getErrorMessage('timeout_error')) as Error & { status: string; trace_id: string }
    error.status = 'timeout_error'
    error.trace_id = createTraceId()
    throw error
  }

  if (query.includes('no context')) {
    return createBusinessErrorResponse('no_relevant_context')
  }

  if (query.includes('retrieval error')) {
    return createBusinessErrorResponse('retrieval_error')
  }

  if (query.includes('model error')) {
    return createBusinessErrorResponse('llm_error')
  }

  return createNormalResponse(query)
}

// Streaming mock: calls onDelta with text chunks, then onDone with final UIMessage
export async function mockSendChatMessageStream(
  payload: { query?: string } | undefined,
  onDelta: (chunk: string) => void,
  onDone: (message: UIMessage) => void,
  onError: (error: Error & { status?: string; trace_id?: string }) => void,
): Promise<void> {
  const query = getQuery(payload)

  try {
    if (query.includes('network error')) {
      await delay(MOCK_LATENCY_MS)
      const error = new Error(getErrorMessage('network_error')) as Error & { status: string; trace_id: string }
      error.status = 'network_error'
      error.trace_id = createTraceId()
      throw error
    }

    if (query.includes('timeout')) {
      await delay(MOCK_LATENCY_MS)
      const error = new Error(getErrorMessage('timeout_error')) as Error & { status: string; trace_id: string }
      error.status = 'timeout_error'
      error.trace_id = createTraceId()
      throw error
    }

    if (query.includes('stream error')) {
      await delay(STREAM_CHUNK_DELAY_MS)
      onDelta('Generating response, but streaming connection error occurred.')
      await delay(STREAM_CHUNK_DELAY_MS)
      const error = new Error(getErrorMessage('stream_error')) as Error & { status: string; trace_id: string }
      error.status = 'stream_error'
      error.trace_id = createTraceId()
      throw error
    }

    // Check business errors before streaming
    if (query.includes('no context')) {
      await delay(MOCK_LATENCY_MS)
      onDone(createBusinessErrorResponse('no_relevant_context'))
      return
    }

    if (query.includes('retrieval error')) {
      await delay(MOCK_LATENCY_MS)
      onDone(createBusinessErrorResponse('retrieval_error'))
      return
    }

    if (query.includes('model error')) {
      await delay(MOCK_LATENCY_MS)
      onDone(createBusinessErrorResponse('llm_error'))
      return
    }

    const answer = query.includes('stream') ? STREAM_ANSWER : NORMAL_ANSWER
    const finalResponse = createNormalResponse(query)

    // Override answer in the final response
    const chunks = splitAnswer(answer)
    for (const chunk of chunks) {
      await delay(STREAM_CHUNK_DELAY_MS)
      onDelta(chunk)
    }

    onDone(finalResponse)
  } catch (error) {
    onError(error as Error & { status?: string; trace_id?: string })
  }
}
