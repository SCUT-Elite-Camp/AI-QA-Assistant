import type { UIMessage } from 'ai'

export interface ChatLike {
  messages: { value: UIMessage[] } | UIMessage[]
  status: { value: 'ready' | 'submitted' | 'streaming' | 'error' } | string
  error: { value: Error | undefined } | Error | undefined
  sendMessage: (params: { text: string; messageId?: string }) => void
  regenerate: (options?: { messageId?: string }) => void
  stop: () => void
}

export interface MockCitation {
  citation_id: number
  title: string
  source_url: string
  doc_id: string
  chunk_id: string
  score: number
  snippet: string
}

export interface MockAgentResponse {
  trace_id: string
  status: string
  answer: string
  message: string
  citations: MockCitation[]
}

export interface MockAgentError extends Error {
  status: string
  trace_id: string
}
