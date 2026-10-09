import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ principal: vi.fn(), findChat: vi.fn(), query: vi.fn() }))
vi.mock('nitro', () => ({ defineHandler: (handler: unknown) => handler,
  HTTPError: class extends Error { constructor(value: { statusMessage: string }) { super(value.statusMessage) } } }))
vi.mock('nitro/h3', () => ({ getQuery: mocks.query }))
vi.mock('../server/utils/attachmentAuth', () => ({ requirePrincipal: mocks.principal }))
vi.mock('../server/utils/drizzle', () => ({
  resetDrizzleForTests: () => {},
  tables: { chats: { id: 'id', userId: 'userId' } },
  useDrizzle: () => ({ query: { chats: { findFirst: mocks.findChat } } }),
}))
vi.mock('drizzle-orm', () => ({ eq: (left: unknown, right: unknown) => [left, right], and: (...values: unknown[]) => values }))
vi.mock('../server/utils/agentConfig', () => ({ getAgentBaseUrl: () => 'http://agent.test' }))
import download from '../server/routes/api/research/download.get'

describe('research report download', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubEnv('AGENT_API_KEY', 'test-token')
    mocks.principal.mockResolvedValue('owner')
    mocks.query.mockReturnValue({ researchId: 'research-abc123' })
    mocks.findChat.mockResolvedValue({ id: 'research-abc123', userId: 'owner' })
  })
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals() })
  it('returns the persisted report as an attachment using server credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ report_id: '../unsafe', markdown: '# Verified report' }))
    vi.stubGlobal('fetch', fetchMock)
    const response = await download({} as never)
    expect(await response.text()).toBe('# Verified report')
    expect(response.headers.get('content-disposition')).toBe('attachment; filename="___unsafe.md"')
    expect(response.headers.get('cache-control')).toBe('private, no-store')
    expect(fetchMock.mock.calls[0][1].headers).toEqual({ Authorization: 'Bearer test-token', 'X-User-ID': 'owner' })
    expect(mocks.findChat.mock.calls[0][0].where).toEqual([['id', 'research-abc123'], ['userId', 'owner']])
  })
  it('rejects an inaccessible conversation before calling the Agent', async () => {
    mocks.findChat.mockResolvedValue(null)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await expect(download({} as never)).rejects.toThrow('not found')
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it('rejects an unauthenticated request', async () => {
    mocks.principal.mockRejectedValue(new Error('login_required'))
    await expect(download({} as never)).rejects.toThrow('login_required')
    expect(mocks.findChat).not.toHaveBeenCalled()
  })
  it('rejects identifiers containing paths', async () => {
    mocks.query.mockReturnValue({ researchId: '../other' })
    await expect(download({} as never)).rejects.toThrow('Invalid research identifier')
    expect(mocks.findChat).not.toHaveBeenCalled()
  })
})
