import { beforeEach, describe, expect, it, vi } from 'vitest'

class MockHTTPError extends Error {
  constructor (readonly options: { statusCode: number, statusMessage: string }) {
    super(options.statusMessage)
  }

  get statusCode () {
    return this.options.statusCode
  }
}

class MockMemoryRepositoryError extends Error {
  constructor (readonly code: 'chat_not_found' | 'fact_not_found' | 'source_message_not_found', message: string) {
    super(message)
  }
}

class MockMemoryFactRevokedError extends Error {}

const mocks = vi.hoisted(() => ({
  confirmFact: vi.fn(),
  createFactProposal: vi.fn(),
  getCurrentRevisionFacts: vi.fn(),
  getValidatedRouterParams: vi.fn(),
  isSensitiveMemoryValue: vi.fn(),
  isSessionFactEnabled: vi.fn(),
  readCurrentRevisionFactSource: vi.fn(),
  readValidatedBody: vi.fn(),
  requireOwnedChat: vi.fn(),
  revokeFact: vi.fn(),
  toFactView: vi.fn(),
  useDrizzle: vi.fn()
}))

vi.mock('nitro', () => ({
  defineHandler: <T>(handler: T) => handler,
  HTTPError: MockHTTPError
}))

vi.mock('nitro/h3', () => ({
  getValidatedRouterParams: mocks.getValidatedRouterParams,
  readValidatedBody: mocks.readValidatedBody
}))

vi.mock('../../server/utils/drizzle', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../server/utils/drizzle')>()
  return { ...actual, useDrizzle: mocks.useDrizzle }
})

vi.mock('../../server/utils/chatAccess', () => ({
  requireOwnedChat: mocks.requireOwnedChat
}))

vi.mock('../../server/utils/sessionFactGate', () => ({
  isSessionFactEnabled: mocks.isSessionFactEnabled
}))

vi.mock('../../server/utils/sensitiveMemoryValue', () => ({
  isSensitiveMemoryValue: mocks.isSensitiveMemoryValue
}))

vi.mock('../../server/utils/memoryRepository', () => ({
  MemoryFactRevokedError: MockMemoryFactRevokedError,
  MemoryRepositoryError: MockMemoryRepositoryError,
  confirmFact: mocks.confirmFact,
  createFactProposal: mocks.createFactProposal,
  getCurrentRevisionFacts: mocks.getCurrentRevisionFacts,
  readCurrentRevisionFactSource: mocks.readCurrentRevisionFactSource,
  revokeFact: mocks.revokeFact,
  toFactView: mocks.toFactView
}))

type RouteHandler = (event: unknown) => Promise<unknown>

const internalFact = {
  category: 'PREFERENCE',
  chatId: 'chat-1',
  confirmedAt: null,
  createdAt: new Date('2026-08-23T00:00:00.000Z'),
  expiresAt: null,
  historyRevision: 3,
  id: 'fact-1',
  proposalKey: 'private-proposal-key',
  revokedAt: null,
  scope: 'SESSION',
  sourceMessageId: 'message-1',
  status: 'PROPOSED',
  value: 'Use concise Chinese responses.'
}

const browserFact = {
  id: internalFact.id,
  category: internalFact.category,
  status: internalFact.status,
  value: internalFact.value,
  sourceMessageId: internalFact.sourceMessageId,
  expiresAt: null,
  confirmedAt: null,
  createdAt: '2026-08-23T00:00:00.000Z'
}

async function loadFactsHandler (): Promise<RouteHandler> {
  const route = await import('../../server/routes/api/chats/[id]/memory/facts.get')
  return route.default as RouteHandler
}

async function loadProposalHandler (): Promise<RouteHandler> {
  const route = await import('../../server/routes/api/chats/[id]/memory/facts/proposals.post')
  return route.default as RouteHandler
}

async function loadConfirmHandler (): Promise<RouteHandler> {
  const route = await import('../../server/routes/api/chats/[id]/memory/facts/[factId]/confirm.post')
  return route.default as RouteHandler
}

async function loadRevokeHandler (): Promise<RouteHandler> {
  const route = await import('../../server/routes/api/chats/[id]/memory/facts/[factId]/revoke.post')
  return route.default as RouteHandler
}

async function expectFactError (result: unknown, status: number, code: string) {
  expect(result).toBeInstanceOf(Response)
  const response = result as Response
  expect(response.status).toBe(status)
  expect(await response.json()).toEqual(expect.objectContaining({ code }))
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getValidatedRouterParams.mockResolvedValue({ factId: 'fact-1', id: 'chat-1' })
  mocks.readValidatedBody.mockResolvedValue({ category: 'PREFERENCE', source_message_id: 'message-1' })
  mocks.requireOwnedChat.mockResolvedValue({
    actor: { isAuthenticated: true, userId: 'user-1' },
    chat: { historyRevision: 3 }
  })
  mocks.isSessionFactEnabled.mockReturnValue(true)
  mocks.isSensitiveMemoryValue.mockReturnValue(false)
  mocks.readCurrentRevisionFactSource.mockResolvedValue({
    historyRevision: 3,
    id: 'message-1',
    parts: [{ text: 'Use concise Chinese responses.', type: 'text' }],
    role: 'user'
  })
  mocks.toFactView.mockReturnValue(browserFact)
  mocks.getCurrentRevisionFacts.mockResolvedValue([internalFact])
  mocks.createFactProposal.mockResolvedValue({ created: true, fact: internalFact })
  mocks.confirmFact.mockResolvedValue(internalFact)
  mocks.revokeFact.mockResolvedValue({ ...internalFact, status: 'REVOKED' })
  mocks.useDrizzle.mockReturnValue({ db: true })
})

describe('Fact lifecycle routes', () => {
  it('checks ownership before the disabled gate and exposes only current-revision FactView records', async () => {
    const handler = await loadFactsHandler()
    mocks.isSessionFactEnabled.mockReturnValue(false)

    await expectFactError(await handler({}), 409, 'session_fact_disabled')
    expect(mocks.requireOwnedChat).toHaveBeenCalledWith({}, 'chat-1')
    expect(mocks.getCurrentRevisionFacts).not.toHaveBeenCalled()

    mocks.isSessionFactEnabled.mockReturnValue(true)
    const result = await handler({})
    expect(result).toEqual({ facts: [browserFact] })
    expect(mocks.getCurrentRevisionFacts).toHaveBeenCalledWith({ db: true }, {
      actorUserId: 'user-1', chatId: 'chat-1', historyRevision: 3
    })
    expect(result).not.toHaveProperty('proposalKey')
  })

  it('keeps Fact routes unavailable to anonymous chat sessions even when the rollout gate is open', async () => {
    const handler = await loadFactsHandler()
    mocks.requireOwnedChat.mockResolvedValueOnce({
      actor: { isAuthenticated: false, userId: 'anonymous-session' },
      chat: { historyRevision: 3 }
    })

    await expectFactError(await handler({}), 409, 'session_fact_disabled')
    expect(mocks.getCurrentRevisionFacts).not.toHaveBeenCalled()
  })

  it.each([
    ['GET facts', loadFactsHandler],
    ['POST proposal', loadProposalHandler],
    ['POST confirm', loadConfirmHandler],
    ['POST revoke', loadRevokeHandler]
  ])('maps an unauthenticated %s request to the stable disabled response body', async (_name, loadHandler) => {
    mocks.requireOwnedChat.mockRejectedValueOnce(new MockHTTPError({
      statusCode: 401,
      statusMessage: 'Authentication required'
    }))

    await expectFactError(await (await loadHandler())({}), 409, 'session_fact_disabled')
  })

  it('maps malformed route parameters and proposal bodies to 09a stable error codes', async () => {
    const facts = await loadFactsHandler()
    mocks.getValidatedRouterParams.mockRejectedValueOnce(new Error('invalid params'))
    await expectFactError(await facts({}), 404, 'not_found')
    expect(mocks.requireOwnedChat).not.toHaveBeenCalled()

    const proposal = await loadProposalHandler()
    mocks.readValidatedBody.mockRejectedValueOnce(new Error('invalid body'))
    await expectFactError(await proposal({}), 422, 'fact_source_not_user_message')
    expect(mocks.createFactProposal).not.toHaveBeenCalled()
  })

  it('uses only server-loaded user text for a manual proposal and never accepts a browser value', async () => {
    const handler = await loadProposalHandler()
    const result = await handler({})

    expect((result as Response).status).toBe(201)
    expect(await (result as Response).json()).toEqual({ created: true, fact: browserFact })
    expect(mocks.createFactProposal).toHaveBeenCalledWith({ db: true }, {
      actorUserId: 'user-1',
      category: 'PREFERENCE',
      chatId: 'chat-1',
      historyRevision: 3,
      sourceMessageId: 'message-1',
      value: 'Use concise Chinese responses.'
    })
  })

  it('rejects non-user and sensitive manual Fact sources without writing a Fact', async () => {
    const handler = await loadProposalHandler()
    mocks.readCurrentRevisionFactSource.mockResolvedValueOnce({
      id: 'message-1', parts: [{ text: 'Assistant text', type: 'text' }], role: 'assistant'
    })
    await expectFactError(await handler({}), 422, 'fact_source_not_user_message')

    mocks.readCurrentRevisionFactSource.mockResolvedValueOnce({
      id: 'message-1', parts: [{ text: 'my password is secret', type: 'text' }], role: 'user'
    })
    mocks.isSensitiveMemoryValue.mockReturnValueOnce(true)
    await expectFactError(await handler({}), 422, 'fact_sensitive')
    expect(mocks.createFactProposal).not.toHaveBeenCalled()
  })

  it('maps cross-user/missing resources to the non-disclosing not_found response', async () => {
    const handler = await loadConfirmHandler()
    mocks.requireOwnedChat.mockRejectedValueOnce(new MockHTTPError({
      statusCode: 404,
      statusMessage: 'Chat not found'
    }))

    await expectFactError(await handler({}), 404, 'not_found')
    expect(mocks.confirmFact).not.toHaveBeenCalled()
  })

  it('keeps confirm/revoke idempotence in the repository and maps a revoked confirmation safely', async () => {
    const confirm = await loadConfirmHandler()
    const revoke = await loadRevokeHandler()

    await expect(confirm({})).resolves.toEqual({ fact: browserFact })
    await expect(confirm({})).resolves.toEqual({ fact: browserFact })
    expect(mocks.confirmFact).toHaveBeenCalledTimes(2)
    expect(mocks.confirmFact).toHaveBeenLastCalledWith({ db: true }, {
      actorUserId: 'user-1', chatId: 'chat-1', factId: 'fact-1', historyRevision: 3
    })

    await expect(revoke({})).resolves.toEqual({ fact: browserFact })
    await expect(revoke({})).resolves.toEqual({ fact: browserFact })
    expect(mocks.revokeFact).toHaveBeenCalledTimes(2)

    mocks.confirmFact.mockRejectedValueOnce(new MockMemoryFactRevokedError())
    await expectFactError(await confirm({}), 409, 'fact_revoked')
  })
})
