import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  findFirst: vi.fn(),
  getValidatedRouterParams: vi.fn(),
  requireTopicRole: vi.fn(),
  useDrizzle: vi.fn()
}))

vi.mock('nitro', () => ({
  defineHandler: <T>(handler: T) => handler,
  HTTPError: class HTTPError extends Error {
    constructor (readonly options: { statusCode: number, statusMessage: string }) {
      super(options.statusMessage)
    }
  }
}))

vi.mock('nitro/h3', () => ({ getValidatedRouterParams: mocks.getValidatedRouterParams }))
vi.mock('../../server/utils/attachmentAuth', () => ({ requireTopicRole: mocks.requireTopicRole }))
vi.mock('../../server/utils/topicStorage', () => ({
  getTopicDocumentsFromDisk: vi.fn(),
  loadTopicFromDisk: vi.fn().mockReturnValue(null)
}))
vi.mock('../../server/utils/drizzle', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../server/utils/drizzle')>()
  return {
    ...actual,
    eq: (column: unknown, value: unknown) => ({ column, value }),
    tables: { ...actual.tables, topics: { id: 'topics.id' } },
    useDrizzle: mocks.useDrizzle
  }
})

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getValidatedRouterParams.mockResolvedValue({ id: 'topic-1' })
  mocks.requireTopicRole.mockResolvedValue({ userId: 'editor-1', role: 'editor' })
  mocks.findFirst.mockResolvedValue({
    id: 'topic-1',
    documents: []
  })
  mocks.useDrizzle.mockReturnValue({ query: { topics: { findFirst: mocks.findFirst } } })
})

describe('Topic API chat mode surface', () => {
  it('does not load nested Chats when returning Topic settings data', async () => {
    const route = await import('../../server/routes/api/topics/[id].get')
    const response = await route.default({})

    const query = mocks.findFirst.mock.calls[0]?.[0]
    expect(query.with).not.toHaveProperty('chats')
    expect(query.with).toHaveProperty('documents', true)
    expect(response).not.toHaveProperty('chats')
  })
})
