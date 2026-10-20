import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  agentFetch: vi.fn(),
  assertSourceDependencies: vi.fn(),
  appendMessage: vi.fn(),
  buildPersistentMemoryContext: vi.fn(),
  callChatWithPersistentFallback: vi.fn(),
  compactAfterSuccessfulAssistantPersistence: vi.fn(),
  createAssistantMessageId: vi.fn(),
  createCurrentMessageHandoff: vi.fn(),
  createUIMessageStream: vi.fn(),
  createUIMessageStreamResponse: vi.fn(),
  getValidatedRouterParams: vi.fn(),
  logMemoryEvent: vi.fn(),
  persistCurrentUserMessage: vi.fn(),
  readValidatedBody: vi.fn(),
  recordAiCall: vi.fn(),
  recordMemoryCompaction: vi.fn(),
  recordMemoryDuration: vi.fn(),
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
vi.mock('../../server/utils/attachmentAuth', () => ({ requireCsrf: vi.fn() }))
vi.mock('../../server/utils/sourceAccess', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../server/utils/sourceAccess')>(),
  assertSourceDependencies: mocks.assertSourceDependencies,
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
  mocks.requireOwnedChat.mockResolvedValue({ actor: { isAuthenticated: true, userId: 'user-1' }, chat: { id: 'chat-1', topicId: null, historyRevision: 3 } })
  mocks.useDrizzle.mockReturnValue({
    query: {
      messages: { findFirst: vi.fn().mockResolvedValue(undefined) },
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
  mocks.createUIMessageStream.mockImplementation((options) => options)
  mocks.createUIMessageStreamResponse.mockImplementation(({ stream }) => stream)

  mocks.agentFetch.mockImplementation(async () => createSseStreamResponse([
    { event: 'citations', data: [] },
    { event: 'token', data: { content: 'ok' } },
    {
      event: 'done',
      data: {
        status: 'success',
        evidence_provenance: { schema_version: 'evidence.provenance.v1', complete: true, dependencies: [] },
        memory_decision: {}
      }
    }
  ]))
})

describe('chat persistence and memory compaction', () => {
  it.each(['accepted', 'forged_quote', 'source_denied'])('only persists and releases authorized display claims: %s', async (mode) => {
    const claims = [{ claim_id: 'claim_1', text: 'Alpha is complete.', start: 0, end: 18,
      supports: [{ citation_id: 1, quote: mode === 'forged_quote' ? 'Invented source' : 'Alpha: complete' }] }]
    mocks.agentFetch.mockResolvedValueOnce(createSseStreamResponse([
      { event: 'answer-claims', data: claims },
      { event: 'citations', data: [{ citation_id: 1, doc_id: 'doc-1', chunk_id: 'c1', title: 'Project status',
        snippet: 'Alpha: complete', evidence_ref: 'ev-a', content_hash: 'hash-a' }] },
      { event: 'answer', data: { content: 'Alpha is complete.[1]' } },
      { event: 'done', data: { status: 'success', evidence_provenance: { schema_version: 'evidence.provenance.v1',
        complete: true, dependencies: [{ source_type: 'knowledge', doc_id: 'doc-1', content_hash: 'hash-a' }] } } },
    ]))
    if (mode === 'source_denied') mocks.assertSourceDependencies.mockRejectedValueOnce(new Error('source_denied'))
    const write = vi.fn()
    await executeChatTurn(false, write)
    if (mode === 'accepted') {
      expect(mocks.appendMessage).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
        parts: expect.arrayContaining([{ type: 'data-answer-claims', data: claims }]),
      }))
      expect(write).toHaveBeenCalledWith({ type: 'data-answer-claims', data: claims })
      expect(mocks.assertSourceDependencies).toHaveBeenCalled()
    } else {
      expect(mocks.appendMessage).not.toHaveBeenCalled()
      expect(write).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'data-answer-claims' }))
    }
  })

  it('shows checked provider deltas before completion and persists only the final answer', async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>
    const encoder = new TextEncoder()
    const proof = { schema_version: 'evidence.provenance.v1', complete: true, dependencies: [] }
    const push = (event: string, data: unknown) => controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`))
    mocks.agentFetch.mockResolvedValueOnce({ ok: true, body: new ReadableStream({ start(value) { controller = value } }) })
    const handler = await loadChatHandler()
    const stream = await handler({})
    let seen!: () => void
    const preview = new Promise<void>(resolve => { seen = resolve })
    const write = vi.fn((part: any) => { if (part.type === 'data-answer-preview' && part.data.delta) seen() })
    const running = stream.execute({ writer: { write } })
    push('source', { evidence_provenance: proof })
    push('token', { content: 'First provider delta' })
    await preview
    expect(mocks.assertSourceDependencies).toHaveBeenCalled()
    expect(mocks.appendMessage).not.toHaveBeenCalled()
    expect(write).toHaveBeenCalledWith(expect.objectContaining({ type: 'data-answer-preview', transient: true,
      data: { messageId: 'message-1:assistant', delta: 'First provider delta' } }))
    push('answer', { content: 'Final checked answer' })
    push('done', { status: 'success', evidence_provenance: proof })
    controller.close()
    await running
    expect(mocks.appendMessage).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
      parts: expect.arrayContaining([{ type: 'text', text: 'Final checked answer' }]),
    }))
    expect(write).toHaveBeenCalledWith(expect.objectContaining({ type: 'data-answer-preview', transient: true,
      data: { messageId: 'message-1:assistant', phase: 'complete', text: 'Final checked answer' } }))
    const completeIndex = write.mock.calls.findIndex(([part]) => part.type === 'data-answer-preview' && part.data.phase === 'complete')
    const finalIndex = write.mock.calls.findIndex(([part]) => part.type === 'text-delta' && part.delta === 'Final checked answer')
    expect(completeIndex).toBeLessThan(finalIndex)
    expect(mocks.appendMessage.mock.invocationCallOrder[0]).toBeLessThan(write.mock.invocationCallOrder[completeIndex]!)
  })

  it('does not preview a token after current source verification fails', async () => {
    mocks.assertSourceDependencies.mockRejectedValueOnce(new Error('source_access_revoked'))
    const write = vi.fn()
    await executeChatTurn(false, write)
    expect(mocks.appendMessage).not.toHaveBeenCalled()
  })
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
    // The answer is durable before release; abort suppresses post-turn effects.
    expect(mocks.appendMessage).toHaveBeenCalledTimes(1)
  })

  it('uses the persisted Chat mode for Agent requests instead of a client-supplied override', async () => {
    mocks.requireOwnedChat.mockResolvedValueOnce({
      actor: { isAuthenticated: true, userId: 'user-1' },
      chat: { id: 'chat-1', topicId: null, title: 'Memory chat', weightMode: 'thinking', messages: [] }
    })
    mocks.readValidatedBody.mockResolvedValueOnce({
      weightMode: 'fast',
      messages: [{ id: 'message-1', parts: [{ text: 'Remember this.', type: 'text' }], role: 'user' }]
    })

    await executeChatTurn(false)

    const requestBody = JSON.parse(mocks.agentFetch.mock.calls[0]?.[1]?.body)
    expect(requestBody.weight_mode).toBe('thinking')
    expect(mocks.useDrizzle.mock.results[0]?.value.update).toBeUndefined()
  })

  it('keeps the already durable answer but suppresses post-turn writes after client abort', async () => {
    await executeChatTurn(true)

    expect(mocks.appendMessage).toHaveBeenCalledOnce()
    expect(mocks.compactAfterSuccessfulAssistantPersistence).not.toHaveBeenCalled()
  })

  it('rejects an unprovenanced stream rather than trusting a public fallback', async () => {
    mocks.agentFetch.mockImplementationOnce(async () => createSseStreamResponse([
      { event: 'token', data: { content: 'public fallback answer' } },
      { event: 'done', data: { status: 'success' } }
    ]))

    await executeChatTurn(false)

    expect(mocks.appendMessage).not.toHaveBeenCalled()
    expect(mocks.compactAfterSuccessfulAssistantPersistence).not.toHaveBeenCalled()
  })

  it('emits citations output when the Agent supplied citations', async () => {
    mocks.agentFetch.mockImplementationOnce(async () => createSseStreamResponse([
      {
        event: 'citations',
        data: [{ doc_id: 'doc-1', chunk_id: 'chunk-1', title: 'Source', source_url: 'https://example.test', snippet: 'Evidence.', evidence_ref: 'ev:doc-1:chunk-1:v1', content_hash: 'source-hash' }]
      },
      { event: 'token', data: { content: 'Answer with a source.' } },
      { event: 'done', data: { status: 'success', evidence_provenance: { schema_version: 'evidence.provenance.v1', complete: true, dependencies: [{ source_type: 'knowledge', doc_id: 'doc-1', content_hash: 'source-hash' }] } } }
    ]))

    const write = vi.fn()
    await executeChatTurn(false, write)

    expect(write).toHaveBeenCalledWith({ type: 'start', messageId: 'assistant-1' })
    expect(mocks.appendMessage).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ id: 'message-1:assistant' }))

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
      { event: 'token', data: { content: 'An unverified model assertion must not be released.' } },
      {
        event: 'done',
        data: {
          status: 'no_relevant_context',
          evidence_provenance: { schema_version: 'evidence.provenance.v1', complete: true, dependencies: [] }
        }
      }
    ]))

    const write = vi.fn()
    await executeChatTurn(false, write)

    expect(write).toHaveBeenCalledWith({ type: 'text-delta', id: 'no-context:message-1:assistant', delta: expect.stringContaining('does not contain enough evidence') })
    expect(write).toHaveBeenCalledWith({ type: 'data-answer-status', data: { status: 'no_relevant_context', persisted: false } })
    expect(JSON.stringify(write.mock.calls)).not.toContain('An unverified model assertion')
    expect(write).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
    expect(mocks.compactAfterSuccessfulAssistantPersistence).not.toHaveBeenCalled()
    expect(mocks.appendMessage).not.toHaveBeenCalled()
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
      delta: expect.stringContaining('No answer is being released')
    }))
    expect(mocks.appendMessage).not.toHaveBeenCalled()
  })

  it('explains daily model quota without releasing provider details or saving an answer', async () => {
    mocks.agentFetch.mockImplementationOnce(async () => createSseStreamResponse([
      { event: 'error', data: { message: 'LLM API returned status 429: free-models-per-day; secret-provider-body' } },
    ]))
    const write = vi.fn()
    await executeChatTurn(false, write)
    expect(write).toHaveBeenCalledWith({ type: 'data-answer-status', data: { status: 'model_daily_quota', persisted: false } })
    expect(write).toHaveBeenCalledWith(expect.objectContaining({ type: 'text-delta', delta: expect.stringContaining('daily free quota') }))
    expect(JSON.stringify(write.mock.calls)).not.toContain('secret-provider-body')
    expect(mocks.appendMessage).not.toHaveBeenCalled()
    expect(mocks.compactAfterSuccessfulAssistantPersistence).not.toHaveBeenCalled()
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

})
