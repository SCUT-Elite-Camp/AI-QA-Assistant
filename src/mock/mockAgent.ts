import type { UIMessage } from 'ai'
import { getErrorMessage } from './errorMap'

const MOCK_LATENCY_MS = 300
const STREAM_CHUNK_DELAY_MS = 120

const NORMAL_ANSWER =
  '这是 Mock Agent 返回的回答。Web Layer MVP 已升级为 TypeScript 全栈架构，集成 AI SDK 流式对话、Nuxt UI 组件库、Nitro 后端和 Drizzle 持久化。当前为 Mock 模式，可输入不同关键词测试各种场景。'

const STREAM_ANSWER =
  '这是 Mock Agent 的流式回答。前端会逐段接收内容并追加到助手消息中，等全部片段返回后再结束 loading 状态。当前为 TypeScript 全栈架构的流式模拟。'

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

    if (/[，。；：、\s]/u.test(char) || buffer.length >= 8) {
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
  const isNoLink = query.includes('无链接')
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
              title: 'Q1 Web Layer MVP 说明',
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

  if (query.includes('网络异常')) {
    const error = new Error(getErrorMessage('network_error')) as Error & { status: string; trace_id: string }
    error.status = 'network_error'
    error.trace_id = createTraceId()
    throw error
  }

  if (query.includes('超时')) {
    const error = new Error(getErrorMessage('timeout_error')) as Error & { status: string; trace_id: string }
    error.status = 'timeout_error'
    error.trace_id = createTraceId()
    throw error
  }

  if (query.includes('无相关')) {
    return createBusinessErrorResponse('no_relevant_context')
  }

  if (query.includes('检索异常')) {
    return createBusinessErrorResponse('retrieval_error')
  }

  if (query.includes('模型异常')) {
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
    if (query.includes('网络异常')) {
      await delay(MOCK_LATENCY_MS)
      const error = new Error(getErrorMessage('network_error')) as Error & { status: string; trace_id: string }
      error.status = 'network_error'
      error.trace_id = createTraceId()
      throw error
    }

    if (query.includes('超时')) {
      await delay(MOCK_LATENCY_MS)
      const error = new Error(getErrorMessage('timeout_error')) as Error & { status: string; trace_id: string }
      error.status = 'timeout_error'
      error.trace_id = createTraceId()
      throw error
    }

    if (query.includes('流式异常')) {
      await delay(STREAM_CHUNK_DELAY_MS)
      onDelta('正在生成回答，但流式连接发生异常。')
      await delay(STREAM_CHUNK_DELAY_MS)
      const error = new Error(getErrorMessage('stream_error')) as Error & { status: string; trace_id: string }
      error.status = 'stream_error'
      error.trace_id = createTraceId()
      throw error
    }

    // Check business errors before streaming
    if (query.includes('无相关')) {
      await delay(MOCK_LATENCY_MS)
      onDone(createBusinessErrorResponse('no_relevant_context'))
      return
    }

    if (query.includes('检索异常')) {
      await delay(MOCK_LATENCY_MS)
      onDone(createBusinessErrorResponse('retrieval_error'))
      return
    }

    if (query.includes('模型异常')) {
      await delay(MOCK_LATENCY_MS)
      onDone(createBusinessErrorResponse('llm_error'))
      return
    }

    const answer = query.includes('流式') ? STREAM_ANSWER : NORMAL_ANSWER
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
