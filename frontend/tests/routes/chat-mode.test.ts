import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getOptionalChatActor: vi.fn(),
  getValidatedRouterParams: vi.fn(),
  isChatOwnedByActor: vi.fn(),
  readValidatedBody: vi.fn(),
  requireCsrf: vi.fn(),
  requireTopicRole: vi.fn(),
  findFirst: vi.fn(),
  returning: vi.fn(),
  set: vi.fn(),
  update: vi.fn(),
  useDrizzle: vi.fn(),
  where: vi.fn()
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

vi.mock('../../server/utils/chatAccess', () => ({
  getOptionalChatActor: mocks.getOptionalChatActor,
  isChatOwnedByActor: mocks.isChatOwnedByActor
}))

vi.mock('../../server/utils/attachmentAuth', () => ({
  requireCsrf: mocks.requireCsrf,
  requireTopicRole: mocks.requireTopicRole
}))

vi.mock('../../server/utils/drizzle', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../server/utils/drizzle')>()
  return {
    ...actual,
    eq: (column: unknown, value: unknown) => ({ column, value }),
    tables: { ...actual.tables, chats: { id: 'chats.id', weightMode: 'chats.weight_mode' } },
    useDrizzle: mocks.useDrizzle
  }
})

type ModeHandler = (event: unknown) => Promise<{ weightMode: string }>

async function loadHandler (): Promise<ModeHandler> {
  const route = await import('../../server/routes/api/chats/[id]/mode.patch')
  return route.default as ModeHandler
}

async function invokeHandler () {
  const handler = await loadHandler()
  return handler({})
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getValidatedRouterParams.mockResolvedValue({ id: 'chat-1' })
  mocks.readValidatedBody.mockResolvedValue({ weightMode: 'thinking' })
  mocks.getOptionalChatActor.mockResolvedValue({ userId: 'editor-1', isAuthenticated: true })
  mocks.isChatOwnedByActor.mockImplementation((ownerId, actor) => ownerId === actor.userId)
  mocks.findFirst.mockResolvedValue({ id: 'chat-1', userId: 'owner-1', topicId: 'topic-1' })
  mocks.requireTopicRole.mockResolvedValue({ userId: 'editor-1', role: 'editor' })
  mocks.returning.mockResolvedValue([{ weightMode: 'thinking' }])
  mocks.where.mockReturnValue({ returning: mocks.returning })
  mocks.set.mockReturnValue({ where: mocks.where })
  mocks.update.mockReturnValue({ set: mocks.set })
  mocks.useDrizzle.mockReturnValue({
    query: { chats: { findFirst: mocks.findFirst } },
    update: mocks.update
  })
})

describe('chat mode authorization', () => {
  it('allows a Topic editor to update a Chat they do not own', async () => {
    await expect(invokeHandler()).resolves.toEqual({ weightMode: 'thinking' })

    expect(mocks.requireTopicRole).toHaveBeenCalledWith({}, 'topic-1', 'editor')
    expect(mocks.set).toHaveBeenCalledWith({ weightMode: 'thinking' })
  })

  it('allows a Chat owner even when the Chat belongs to a Topic they cannot edit', async () => {
    mocks.getOptionalChatActor.mockResolvedValueOnce({ userId: 'owner-1', isAuthenticated: true })

    await expect(invokeHandler()).resolves.toEqual({ weightMode: 'thinking' })

    expect(mocks.requireTopicRole).not.toHaveBeenCalled()
  })

  it('rejects a Topic viewer who does not own the Chat', async () => {
    mocks.requireTopicRole.mockRejectedValueOnce(Object.assign(new Error('topic_forbidden'), {
      options: { statusCode: 403, statusMessage: 'topic_forbidden' }
    }))

    await expect(invokeHandler()).rejects.toMatchObject({
      options: { statusCode: 403, statusMessage: 'topic_forbidden' }
    })
    expect(mocks.set).not.toHaveBeenCalled()
  })

  it('rejects a non-owner of a standalone Chat', async () => {
    mocks.findFirst.mockResolvedValueOnce({ id: 'chat-1', userId: 'owner-1', topicId: null })

    await expect(invokeHandler()).rejects.toMatchObject({
      options: { statusCode: 404, statusMessage: 'Chat not found' }
    })
    expect(mocks.requireTopicRole).not.toHaveBeenCalled()
    expect(mocks.set).not.toHaveBeenCalled()
  })
})
