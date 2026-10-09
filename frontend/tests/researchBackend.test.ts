import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HTTPEvent } from 'nitro/h3'

const mocks = vi.hoisted(() => ({ actor: vi.fn(), user: vi.fn(), agent: vi.fn(), csrf: vi.fn(), body: vi.fn() }))
vi.mock('../server/utils/session', () => ({ useUserSession: async () => ({ data: { user: { id: await mocks.actor() } } }) }))
vi.mock('../server/utils/drizzle', () => ({ eq: vi.fn(), tables: { users: { id: 'id' } },
  resetDrizzleForTests: vi.fn(),
  useDrizzle: () => ({ query: { users: { findFirst: mocks.user } } }) }))
vi.mock('../server/utils/agent-client', () => ({ agentFetch: mocks.agent }))
vi.mock('../server/utils/attachmentAuth', () => ({ requireCsrf: mocks.csrf }))
vi.mock('nitro/h3', async importOriginal => ({ ...await importOriginal<object>(), readBody: mocks.body }))
import { fetchResearchBackend, proxyResearchRequest, requireResearchActor, researchBackendPath } from '../server/utils/researchBackend'

beforeEach(() => {
  vi.resetAllMocks()
  mocks.actor.mockResolvedValue('alice')
  mocks.user.mockResolvedValue({ id: 'alice', disabled: false })
  mocks.agent.mockResolvedValue(new Response('{}', { status: 200 }))
  mocks.body.mockResolvedValue({ query: '真实问题' })
})

describe('trusted Research proxy', () => {
  it('uses the enabled session identity and ignores browser credentials', async () => {
    const event = { req: new Request('http://web/api/research/jobs', { method: 'POST', headers: {
      'X-User-ID': 'admin', Authorization: 'Bearer browser-key',
    } }) } as HTTPEvent
    await proxyResearchRequest(event, 'jobs')
    expect(mocks.csrf).toHaveBeenCalledWith(event)
    const options = mocks.agent.mock.calls[0]![1]
    expect(options.headers).toEqual({ 'X-User-ID': 'alice' })
    expect(options.redirect).toBe('error')
  })
  it('rejects absent and disabled live users', async () => {
    mocks.user.mockResolvedValue(undefined)
    await expect(requireResearchActor({} as HTTPEvent)).rejects.toMatchObject({ status: 401 })
    mocks.user.mockResolvedValue({ disabled: true })
    await expect(requireResearchActor({} as HTTPEvent)).rejects.toMatchObject({ status: 403 })
    expect(mocks.agent).not.toHaveBeenCalled()
  })
  it('preserves permission failures and disables response caching', async () => {
    mocks.agent.mockResolvedValue(new Response('{"detail":"revoked"}', { status: 403 }))
    const response = await fetchResearchBackend('alice', 'jobs/research-123/report')
    expect(response.status).toBe(403)
    expect(response.headers.get('Cache-Control')).toBe('private, no-store')
  })
  it.each(['../chat', 'jobs/research-1/documents/%252e%252e/source',
    'jobs/research-1/documents/a%2fb/source', 'http://evil', 'jobs/research-1/report?evil'])('rejects unsafe or unlisted paths: %s', path => {
    expect(() => researchBackendPath(path, 'GET')).toThrow()
  })
})
