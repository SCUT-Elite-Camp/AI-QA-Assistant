import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const mocks = vi.hoisted(() => ({ createJob: vi.fn(), persist: vi.fn(), push: vi.fn(), fetchChats: vi.fn(), fetchSession: vi.fn() }))
const user = ref<{ id: string } | null>({ id: 'test-user' })
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
vi.mock('ofetch', () => ({ $fetch: mocks.persist }))
vi.mock('../src/composables/useResearchApi', () => ({ useResearchApi: () => ({ createJob: mocks.createJob }) }))
vi.mock('../src/composables/useChats', () => ({ useChats: () => ({ fetchChats: mocks.fetchChats }) }))
vi.mock('../src/composables/useCsrf', () => ({ useCsrf: () => ({ csrf: () => 'test-token', headerName: 'x-csrf-token' }) }))
vi.mock('../src/composables/useUserSession', () => ({ useUserSession: () => ({ user, fetchSession: mocks.fetchSession }) }))
import { useResearchLaunch } from '../src/composables/useResearchLaunch'

beforeEach(() => {
  vi.resetAllMocks()
  user.value = { id: 'test-user' }
  mocks.createJob.mockResolvedValue({ research_id: 'research-test' })
})

describe('research launch', () => {
  it('preserves long questions while bounding the source topic to the API limit', async () => {
    const query = 'Compare dates and integration limitations. '.repeat(8).trim()
    expect(await useResearchLaunch().launchResearch(query, ['doc'])).toBe(true)
    expect(mocks.createJob.mock.calls[0][0].query).toBe(query)
    expect(mocks.createJob.mock.calls[0][0].source_scope.topic).toBe(query.slice(0, 200))
  })
  it('requires a selected source and a signed-in session before creating a job', async () => {
    const launch = useResearchLaunch()
    expect(await launch.launchResearch('English question')).toBe(false)
    expect(mocks.createJob).not.toHaveBeenCalled()
    user.value = null
    expect(await launch.launchResearch('English question', ['doc'])).toBe(false)
    expect(mocks.fetchSession).toHaveBeenCalledOnce()
    expect(mocks.createJob).not.toHaveBeenCalled()
    expect(launch.researchLaunchError.value).toContain('Sign in')
  })

  it('freezes deduplicated sources and requests an English report', async () => {
    const launch = useResearchLaunch()
    expect(await launch.launchResearch('  Compare the sprints. ', ['b', 'a', 'b'])).toBe(true)
    expect(mocks.createJob).toHaveBeenCalledWith(expect.objectContaining({
      query: 'Compare the sprints.', source_scope: { knowledge_base_ids: [], document_ids: ['a', 'b'], topic: 'Compare the sprints.' },
      report_spec: expect.objectContaining({ language: 'en-US' }),
    }))
    expect(mocks.persist).toHaveBeenCalledWith('/api/research/chats', expect.objectContaining({ body: { researchId: 'research-test', query: 'Compare the sprints.' } }))
    expect(mocks.push).toHaveBeenCalledWith('/research/research-test')
  })

  it('reuses a created job when conversation persistence temporarily fails', async () => {
    mocks.persist.mockRejectedValueOnce(new Error('Temporary database error'))
    const launch = useResearchLaunch()
    expect(await launch.launchResearch('Compare the sprints.', ['b', 'a'])).toBe(false)
    expect(launch.researchLaunchError.value).toContain('Temporary database error')
    expect(launch.launchingResearch.value).toBe(false)
    expect(await launch.launchResearch('Compare the sprints.', ['a', 'b'])).toBe(true)
    expect(mocks.createJob).toHaveBeenCalledOnce()
    expect(mocks.persist).toHaveBeenCalledTimes(2)
  })

  it('ignores double submission while the first request is pending', async () => {
    let resolveJob!: (job: { research_id: string }) => void
    mocks.createJob.mockImplementation(() => new Promise(resolve => { resolveJob = resolve }))
    const launch = useResearchLaunch()
    const first = launch.launchResearch('Compare the sprints.', ['a'])
    expect(await launch.launchResearch('Compare the sprints.', ['a'])).toBe(false)
    resolveJob({ research_id: 'research-test' })
    expect(await first).toBe(true)
    expect(mocks.createJob).toHaveBeenCalledOnce()
  })
})
