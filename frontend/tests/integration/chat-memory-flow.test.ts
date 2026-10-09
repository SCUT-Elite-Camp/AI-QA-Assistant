import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  agentFetch: vi.fn(),
  appendMessage: vi.fn(),
  buildPersistentMemoryContext: vi.fn(),
  callChatWithPersistentFallback: vi.fn(),
  compactAfterSuccessfulAssistantPersistence: vi.fn(),
  createAssistantMessageId: vi.fn(),
  createCurrentMessageHandoff: vi.fn(),
  createFactProposal: vi.fn(),
  createUIMessageStream: vi.fn(),
  createUIMessageStreamResponse: vi.fn(),
  getValidatedRouterParams: vi.fn(),
  isSensitiveMemoryValue: vi.fn(),
  isSessionFactEnabled: vi.fn(),
  logMemoryEvent: vi.fn(),
  persistCurrentUserMessage: vi.fn(),
  readCurrentRevisionFactSource: vi.fn(),
  readValidatedBody: vi.fn(),
  recordAiCall: vi.fn(),
  recordMemoryCompaction: vi.fn(),
  recordMemoryDuration: vi.fn(),
  recordMemoryFact: vi.fn(),
  recordMemoryFallback: vi.fn(),
  recordMemoryResolve: vi.fn(),
  requireOwnedChat: vi.fn(),
  shouldUsePersistentMemory: vi.fn(),
  useDrizzle: vi.fn()
}))

vi.mock('ai', () => ({
  createUIMessageStream: mocks.createUIMessageStream,
  createUIMessageStreamResponse: mocks.createUIMessageStreamResponse
}))

vi.mock('nitro', () => ({
  defineHandler: <T>(handler: T) => handler,
  HTTPError: class HTTPError extends Error {
    constructor (readonly options: { statusCode: number, statusMessage: string }) {
      super(options.statusMessage)
    }
  }
}))

vi.mock('nitro/h3', () => ({
  getValidatedRouterParams: mocks.getValidatedRouterParams,
  readValidatedBody: mocks.readValidatedBody
}))

vi.mock('../../server/utils/drizzle', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../server/utils/drizzle')>()
  return { ...actual, useDrizzle: mocks.useDrizzle }
})

vi.mock('../../server/utils/agent-client', () => ({
  agentFetch: mocks.agentFetch,
  agentHeaders: vi.fn().mockReturnValue({})
}))

vi.mock('../../server/utils/metrics', () => ({
  recordAiCall: mocks.recordAiCall,
  recordMemoryCompaction: mocks.recordMemoryCompaction,
  recordMemoryDuration: mocks.recordMemoryDuration,
  recordMemoryFact: mocks.recordMemoryFact,
  recordMemoryFallback: mocks.recordMemoryFallback,
  recordMemoryResolve: mocks.recordMemoryResolve
}))
vi.mock('../../server/utils/logger', () => ({ logMemoryEvent: mocks.logMemoryEvent }))
vi.mock('../../server/utils/topicStorage', () => ({ ensureTopicDir: vi.fn(), syncTopicToDisk: vi.fn(), syncAllTopicDocuments: vi.fn(), loadTopicFromDisk: vi.fn() }))
vi.mock('../../server/utils/chatAccess', () => ({
  requireOwnedChat: mocks.requireOwnedChat
}))
vi.mock('../../server/utils/agentInternalClient', () => ({
  callChatWithPersistentFallback: mocks.callChatWithPersistentFallback,
  shouldUsePersistentMemory: mocks.shouldUsePersistentMemory
}))
vi.mock('../../server/utils/postTurnCompaction', () => ({
  compactAfterSuccessfulAssistantPersistence: mocks.compactAfterSuccessfulAssistantPersistence
}))
vi.mock('../../server/utils/persistentMemoryContext', () => ({
  buildPersistentMemoryContext: mocks.buildPersistentMemoryContext
}))
vi.mock('../../server/utils/memoryRepository', () => ({
  createFactProposal: mocks.createFactProposal,
  readCurrentRevisionFactSource: mocks.readCurrentRevisionFactSource
}))
vi.mock('../../server/utils/sensitiveMemoryValue', () => ({
  isSensitiveMemoryValue: mocks.isSensitiveMemoryValue
}))
vi.mock('../../server/utils/sessionFactGate', () => ({
  isSessionFactEnabled: mocks.isSessionFactEnabled
}))
vi.mock('../../server/utils/messageLifecycle', () => ({
  appendMessage: mocks.appendMessage,
  createAssistantMessageId: mocks.createAssistantMessageId,
  createAssistantStreamState: () => ({
    agentSucceeded: false,
    assistantContent: '',
    clientAborted: false,
    streamCompleted: false,
    streamFailed: false
  }),
  createCurrentMessageHandoff: mocks.createCurrentMessageHandoff,
  persistCurrentUserMessage: mocks.persistCurrentUserMessage,
  shouldPersistAssistantMessage: (state: {
    agentSucceeded: boolean
    assistantContent: string
    clientAborted: boolean
    streamCompleted: boolean
    streamFailed: boolean
  }) => state.agentSucceeded
    && state.streamCompleted
    && !state.clientAborted
    && !state.streamFailed
    && Boolean(state.assistantContent.trim())
}))

type ChatStream = {
  execute: (input: { writer: { write: (chunk: unknown) => void } }) => Promise<void>
  onFinish: (input: { isAborted: boolean }) => Promise<void>
}

type ChatHandler = (event: unknown) => Promise<ChatStream>

function createSseStreamResponse(events: Array<{ event?: string, data: any }>, status = 200, statusText = 'OK') {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      for (const item of events) {
        let chunk = ''
        if (item.event) chunk += `event: ${item.event}\n`
        chunk += `data: ${JSON.stringify(item.data)}\n\n`
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    }
  })
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    body: stream
  }
}

async function loadChatHandler (): Promise<ChatHandler> {
  const route = await import('../../server/routes/api/chats/[id].post')
  return route.default as ChatHandler
}

async function executeChatTurn (isAborted: boolean, write = vi.fn()) {
  const handler = await loadChatHandler()
  const stream = await handler({})
  await stream.execute({ writer: { write } })
  await stream.onFinish({ isAborted })
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getValidatedRouterParams.mockResolvedValue({ id: 'chat-1' })
  mocks.readValidatedBody.mockResolvedValue({
    messages: [{ id: 'message-1', parts: [{ text: 'Remember this.', type: 'text' }], role: 'user' }]
  })
  mocks.requireOwnedChat.mockResolvedValue({ actor: { isAuthenticated: true, userId: 'user-1' } })
  mocks.useDrizzle.mockReturnValue({
    query: {
      chats: {
        findFirst: vi.fn().mockResolvedValue({
          id: 'chat-1',
          messages: [],
          title: 'Memory chat',
          topicId: null
        })
      }
    }
  })
  mocks.persistCurrentUserMessage.mockResolvedValue({
    chatId: 'chat-1', historyRevision: 3, id: 'message-1', role: 'user', sequence: 7
  })
  mocks.createCurrentMessageHandoff.mockReturnValue({
    actorUserId: 'user-1', chatId: 'chat-1', currentMessageId: 'message-1', currentSequence: 7, historyRevision: 3
  })
  mocks.shouldUsePersistentMemory.mockReturnValue(true)
  mocks.buildPersistentMemoryContext.mockResolvedValue({ memory: 'context' })
  mocks.createAssistantMessageId.mockReturnValue('assistant-1')
  mocks.appendMessage.mockResolvedValue({ chatId: 'chat-1', historyRevision: 3, id: 'assistant-1' })
  mocks.isSessionFactEnabled.mockReturnValue(true)
  mocks.readCurrentRevisionFactSource.mockResolvedValue({
    id: 'message-1',
    parts: [{ text: 'Remember this.', type: 'text' }],
    role: 'user'
  })
  mocks.isSensitiveMemoryValue.mockReturnValue(false)
  mocks.createFactProposal.mockResolvedValue({ created: true, fact: { id: 'fact-1' } })
  mocks.createUIMessageStream.mockImplementation((options) => options)
  mocks.createUIMessageStreamResponse.mockImplementation(({ stream }) => stream)

  mocks.agentFetch.mockImplementation(async () => createSseStreamResponse([
    { event: 'citations', data: [] },
    { event: 'token', data: { content: 'ok' } },
    {
      event: 'done',
      data: {
        status: 'success',
        memory_decision: {
          fact_proposals: [{
            category: 'PREFERENCE',
            expires_at: 999_999_999_999,
            source_message_id: 'message-1',
            value: 'Use concise Chinese responses.'
          }]
        }
      }
    }
  ]))
})

describe('chat to Fact proposal lifecycle', () => {
  it.each([true, false])('persists after normal response closure only (writableEnded=%s)', async (writableEnded) => {
    let responseClose!: () => void
    const requestOn = vi.fn()
    const handler = await loadChatHandler()
    const stream = await handler({ runtime: { node: {
      req: { on: requestOn },
      res: { writableEnded, on: (_name: string, callback: () => void) => { responseClose = callback } }
    } } })
    expect(requestOn).not.toHaveBeenCalled()
    await stream.execute({ writer: { write: vi.fn() } })
    responseClose()
    await stream.onFinish({ isAborted: false })
    expect(mocks.appendMessage).toHaveBeenCalledTimes(writableEnded ? 1 : 0)
  })
  it('creates an Agent Fact only after assistant persistence and ignores Agent expires_at', async () => {
    await executeChatTurn(false)

    expect(mocks.appendMessage).toHaveBeenCalledOnce()
    expect(mocks.createFactProposal).toHaveBeenCalledWith(expect.anything(), {
      actorUserId: 'user-1',
      category: 'PREFERENCE',
      chatId: 'chat-1',
      historyRevision: 3,
      sourceMessageId: 'message-1',
      value: 'Use concise Chinese responses.'
    })
    expect(mocks.createFactProposal.mock.invocationCallOrder[0]).toBeGreaterThan(
      mocks.appendMessage.mock.invocationCallOrder[0]!
    )
    expect(mocks.createFactProposal.mock.calls[0]![1]).not.toHaveProperty('expiresAt')
    expect(mocks.createFactProposal.mock.calls[0]![1]).not.toHaveProperty('expires_at')
  })

  it('does not persist an assistant row or a Fact after an aborted SSE stream', async () => {
    await executeChatTurn(true)

    expect(mocks.appendMessage).not.toHaveBeenCalled()
    expect(mocks.createFactProposal).not.toHaveBeenCalled()
    expect(mocks.compactAfterSuccessfulAssistantPersistence).not.toHaveBeenCalled()
  })

  it('keeps a public-Agent fallback free of Fact writes even when its body imitates the internal envelope', async () => {
    mocks.agentFetch.mockImplementationOnce(async () => createSseStreamResponse([
      { event: 'token', data: { content: 'public fallback answer' } },
      { event: 'done', data: { status: 'success' } }
    ]))

    await executeChatTurn(false)

    expect(mocks.appendMessage).toHaveBeenCalledOnce()
    expect(mocks.createFactProposal).not.toHaveBeenCalled()
    expect(mocks.compactAfterSuccessfulAssistantPersistence).not.toHaveBeenCalled()
  })

  it('emits a recall label only for a handled private internal response', async () => {
    mocks.agentFetch.mockImplementationOnce(async () => createSseStreamResponse([
      { event: 'token', data: { content: 'Confirmed memory.' } },
      {
        event: 'done',
        data: {
          status: 'success',
          memory_decision: {
            fact_proposals: [],
            recall: { answer: 'Confirmed memory.', handled: true }
          }
        }
      }
    ]))

    const write = vi.fn()
    await executeChatTurn(false, write)

    expect(write).toHaveBeenCalledWith({
      type: 'data-memory-recall',
      data: { messageId: 'assistant-1' }
    })
  })

  it('emits citations output when the Agent supplied citations', async () => {
    mocks.agentFetch.mockImplementationOnce(async () => createSseStreamResponse([
      {
        event: 'citations',
        data: [{ doc_id: 'doc-1', chunk_id: 'chunk-1', title: 'Source', source_url: 'https://example.test', snippet: 'Evidence.' }]
      },
      { event: 'token', data: { content: 'Answer with a source.' } },
      { event: 'done', data: { status: 'success' } }
    ]))

    const write = vi.fn()
    await executeChatTurn(false, write)

    expect(write).toHaveBeenCalledWith({ type: 'start', messageId: 'assistant-1' })
    expect(mocks.appendMessage).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ id: 'assistant-1' }))

    expect(write).toHaveBeenCalledWith(expect.objectContaining({
      type: 'tool-output-available'
    }))
    const emitted = write.mock.calls.map(([value]) => value).find(value => value.type === 'tool-output-available')
    expect(mocks.appendMessage).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
      parts: expect.arrayContaining([expect.objectContaining({
        type: 'tool-rag_search', state: 'output-available', output: emitted.output,
      })]),
    }))
  })

  it('streams a private no_relevant_context message without Memory or RAG side effects', async () => {
    mocks.agentFetch.mockImplementationOnce(async () => createSseStreamResponse([
      { event: 'token', data: { content: '当前知识库没有足够信息回答该问题。' } },
      {
        event: 'done',
        data: {
          status: 'no_relevant_context'
        }
      }
    ]))

    const write = vi.fn()
    await executeChatTurn(false, write)

    expect(write).toHaveBeenCalledWith({ type: 'text-delta', id: 'assistant-1', delta: '当前知识库没有足够信息回答该问题。' })
    expect(write).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
    expect(write).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'data-memory-recall' }))
    expect(mocks.createFactProposal).not.toHaveBeenCalled()
    expect(mocks.compactAfterSuccessfulAssistantPersistence).not.toHaveBeenCalled()
  })

  it('handles agent errors gracefully without throwing', async () => {
    mocks.agentFetch.mockImplementationOnce(async () => ({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      body: null
    }))

    const write = vi.fn()
    await executeChatTurn(false, write)

    expect(write).toHaveBeenCalledWith(expect.objectContaining({
      type: 'text-delta',
      delta: expect.stringContaining('Unable to generate an answer')
    }))
    expect(mocks.appendMessage).not.toHaveBeenCalled()
  })

  it('never logs the user query or a rejected Fact value', async () => {
    const queryText = '记住目标：my password is private'
    const consoleLog = vi.spyOn(console, 'log').mockImplementation(() => undefined)
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    mocks.readValidatedBody.mockResolvedValueOnce({
      messages: [{ id: 'message-1', parts: [{ text: queryText, type: 'text' }], role: 'user' }]
    })
    mocks.readCurrentRevisionFactSource.mockResolvedValueOnce({
      id: 'message-1', parts: [{ text: queryText, type: 'text' }], role: 'user'
    })
    mocks.isSensitiveMemoryValue.mockReturnValueOnce(true)

    try {
      await executeChatTurn(false)
      const logText = JSON.stringify([...consoleLog.mock.calls, ...consoleWarn.mock.calls])
      expect(logText).not.toContain(queryText)
      expect(logText).not.toContain('my password is private')
    } finally {
      consoleLog.mockRestore()
      consoleWarn.mockRestore()
    }
  })

  it('absorbs a proposal write failure after the assistant row is durable', async () => {
    mocks.createFactProposal.mockRejectedValueOnce(new Error('temporary database failure'))

    await expect(executeChatTurn(false)).resolves.toBeUndefined()
    expect(mocks.appendMessage).toHaveBeenCalledOnce()
    expect(mocks.createFactProposal).toHaveBeenCalledOnce()
  })

  it('absorbs a compaction failure after the assistant row is durable', async () => {
    mocks.compactAfterSuccessfulAssistantPersistence.mockRejectedValueOnce(
      new Error('Agent compaction unavailable')
    )

    await expect(executeChatTurn(false)).resolves.toBeUndefined()

    expect(mocks.appendMessage).toHaveBeenCalledOnce()
    expect(mocks.compactAfterSuccessfulAssistantPersistence).toHaveBeenCalledOnce()
    expect(mocks.compactAfterSuccessfulAssistantPersistence.mock.invocationCallOrder[0]).toBeGreaterThan(
      mocks.appendMessage.mock.invocationCallOrder[0]!
    )
    expect(mocks.recordMemoryCompaction).toHaveBeenCalledWith('failed')
  })

  it('drops mismatched, invalid, non-user, and sensitive Agent proposals without altering the successful chat path', async () => {
    const { persistAgentFactProposalsAfterAssistantPersistence } = await import('../../server/routes/api/chats/[id].post')
    mocks.readCurrentRevisionFactSource.mockResolvedValueOnce({
      id: 'message-1', parts: [{ text: 'Remember this.', type: 'text' }], role: 'user'
    })
    await expect(persistAgentFactProposalsAfterAssistantPersistence({} as never, {
      actorUserId: 'user-1',
      chatId: 'chat-1',
      currentMessageId: 'message-1',
      historyRevision: 3,
      proposals: [{
        category: 'GOAL', expires_at: null, source_message_id: 'another-message', value: 'Finish this task.'
      }]
    })).resolves.toBeUndefined()

    mocks.readCurrentRevisionFactSource.mockResolvedValueOnce({
      id: 'message-1', parts: [{ text: 'Remember this.', type: 'text' }], role: 'user'
    })
    await expect(persistAgentFactProposalsAfterAssistantPersistence({} as never, {
      actorUserId: 'user-1',
      chatId: 'chat-1',
      currentMessageId: 'message-1',
      historyRevision: 3,
      proposals: [{
        category: 'UNKNOWN' as never, expires_at: null, source_message_id: 'message-1', value: 'Finish this task.'
      }]
    })).resolves.toBeUndefined()

    mocks.readCurrentRevisionFactSource.mockResolvedValueOnce({
      id: 'message-1', parts: [{ text: 'secret', type: 'text' }], role: 'assistant'
    })
    await expect(persistAgentFactProposalsAfterAssistantPersistence({} as never, {
      actorUserId: 'user-1',
      chatId: 'chat-1',
      currentMessageId: 'message-1',
      historyRevision: 3,
      proposals: [{
        category: 'GOAL', expires_at: null, source_message_id: 'message-1', value: 'secret'
      }]
    })).resolves.toBeUndefined()

    mocks.readCurrentRevisionFactSource.mockResolvedValueOnce({
      id: 'message-1', parts: [{ text: 'secret', type: 'text' }], role: 'user'
    })
    mocks.isSensitiveMemoryValue.mockReturnValueOnce(true)
    await expect(persistAgentFactProposalsAfterAssistantPersistence({} as never, {
      actorUserId: 'user-1',
      chatId: 'chat-1',
      currentMessageId: 'message-1',
      historyRevision: 3,
      proposals: [{
        category: 'GOAL', expires_at: null, source_message_id: 'message-1', value: 'secret'
      }]
    })).resolves.toBeUndefined()

    expect(mocks.createFactProposal).not.toHaveBeenCalled()
  })
})
