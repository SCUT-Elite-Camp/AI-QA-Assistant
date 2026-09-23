import { beforeEach, describe, expect, it, vi } from 'vitest'

class MockHTTPError extends Error {
  constructor (readonly options: { statusCode: number, statusMessage: string }) {
    super(options.statusMessage)
  }
}

class MockHistoryMutationError extends Error {
  constructor (readonly statusCode: number, message: string) {
    super(message)
  }
}

const mocks = vi.hoisted(() => ({
  and: vi.fn((...clauses: unknown[]) => clauses),
  delete: vi.fn(),
  eq: vi.fn((column: unknown, value: unknown) => ({ column, value })),
  getValidatedRouterParams: vi.fn(),
  readValidatedBody: vi.fn(),
  requireOwnedChat: vi.fn(),
  resetShortWindow: vi.fn(),
  truncateHistoryAndInvalidateMemory: vi.fn(),
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
  return {
    ...actual,
    and: mocks.and,
    eq: mocks.eq,
    tables: {
      ...actual.tables,
      chats: {
        ...actual.tables.chats,
        id: 'chat.id',
        userId: 'chat.userId'
      }
    },
    useDrizzle: mocks.useDrizzle
  }
})

vi.mock('../../server/utils/chatAccess', () => ({
  requireOwnedChat: mocks.requireOwnedChat
}))

vi.mock('../../server/utils/agentInternalClient', () => ({
  resetShortWindow: mocks.resetShortWindow
}))

vi.mock('../../server/utils/memoryRepository', () => ({
  HistoryMutationError: MockHistoryMutationError,
  truncateHistoryAndInvalidateMemory: mocks.truncateHistoryAndInvalidateMemory
}))

type RouteHandler = (event: unknown) => Promise<unknown>

function deferred<T> () {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

async function loadMessageMutationHandler (): Promise<RouteHandler> {
  const route = await import('../../server/routes/api/chats/messages/[id].delete')
  return route.default as RouteHandler
}

async function loadChatDeletionHandler (): Promise<RouteHandler> {
  const route = await import('../../server/routes/api/chats/[id].delete')
  return route.default as RouteHandler
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getValidatedRouterParams.mockResolvedValue({ id: 'chat-1' })
  mocks.readValidatedBody.mockResolvedValue({ messageId: 'message-1', type: 'edit' })
  mocks.requireOwnedChat.mockResolvedValue({ actor: { userId: 'user-1' } })
  mocks.resetShortWindow.mockResolvedValue({ cleared: true })
})

describe('history mutation short-window reset boundary', () => {
  it('calls the private reset only after an edit transaction commits, and a reset failure leaves the response successful', async () => {
    const commit = deferred<{ historyRevision: number }>()
    mocks.truncateHistoryAndInvalidateMemory.mockReturnValue(commit.promise)
    mocks.useDrizzle.mockReturnValue({})
    mocks.resetShortWindow.mockRejectedValue(new Error('agent temporarily unavailable'))
    const handler = await loadMessageMutationHandler()

    const response = handler({})
    expect(mocks.resetShortWindow).not.toHaveBeenCalled()

    commit.resolve({ historyRevision: 2 })

    await expect(response).resolves.toEqual({ success: true, historyRevision: 2 })
    expect(mocks.truncateHistoryAndInvalidateMemory).toHaveBeenCalledWith({}, {
      actorUserId: 'user-1',
      chatId: 'chat-1',
      messageId: 'message-1',
      type: 'edit'
    })
    expect(mocks.resetShortWindow).toHaveBeenCalledOnce()
    expect(mocks.resetShortWindow).toHaveBeenCalledWith('chat-1')
  })

  it('does not reset the short window when the edit transaction fails', async () => {
    mocks.truncateHistoryAndInvalidateMemory.mockRejectedValue(new Error('transaction rolled back'))
    mocks.useDrizzle.mockReturnValue({})
    const handler = await loadMessageMutationHandler()

    await expect(handler({})).rejects.toThrow('transaction rolled back')
    expect(mocks.resetShortWindow).not.toHaveBeenCalled()
  })

  it('calls the private reset only after chat deletion commits, and a reset failure leaves the deletion response intact', async () => {
    const commit = deferred<Array<{ id: string }>>()
    const returning = vi.fn().mockReturnValue(commit.promise)
    const where = vi.fn().mockReturnValue({ returning })
    mocks.useDrizzle.mockReturnValue({
      delete: mocks.delete.mockReturnValue({ where })
    })
    mocks.resetShortWindow.mockRejectedValue(new Error('agent temporarily unavailable'))
    const handler = await loadChatDeletionHandler()

    const response = handler({})
    expect(mocks.resetShortWindow).not.toHaveBeenCalled()

    commit.resolve([{ id: 'chat-1' }])

    await expect(response).resolves.toEqual([{ id: 'chat-1' }])
    expect(mocks.delete).toHaveBeenCalledOnce()
    expect(mocks.resetShortWindow).toHaveBeenCalledOnce()
    expect(mocks.resetShortWindow).toHaveBeenCalledWith('chat-1')
  })

  it('does not reset the short window when chat deletion fails', async () => {
    const returning = vi.fn().mockRejectedValue(new Error('delete rolled back'))
    const where = vi.fn().mockReturnValue({ returning })
    mocks.useDrizzle.mockReturnValue({
      delete: mocks.delete.mockReturnValue({ where })
    })
    const handler = await loadChatDeletionHandler()

    await expect(handler({})).rejects.toThrow('delete rolled back')
    expect(mocks.resetShortWindow).not.toHaveBeenCalled()
  })
})
