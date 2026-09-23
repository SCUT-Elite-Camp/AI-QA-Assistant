import { afterEach, describe, expect, it, vi } from 'vitest'
import { $fetch } from 'ofetch'
import { useSessionFacts } from '../../src/composables/useSessionFacts'

vi.mock('ofetch', () => ({ $fetch: vi.fn() }))

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

function fact(id: string, value: string) {
  return {
    id,
    category: 'GOAL' as const,
    status: 'PROPOSED' as const,
    value,
    sourceMessageId: 'message-1',
    expiresAt: null,
    confirmedAt: null,
    createdAt: '2026-08-23T00:00:00.000Z'
  }
}

const fetchMock = vi.mocked($fetch)

afterEach(() => {
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('Session Fact chat scope', () => {
  it('drops a delayed GET from the previous chat after the active chat changes', async () => {
    const oldResponse = deferred<{ facts: ReturnType<typeof fact>[] }>()
    fetchMock.mockReturnValueOnce(oldResponse.promise as never)
    const sessionFacts = useSessionFacts()

    sessionFacts.activate('chat-a')
    const oldLoad = sessionFacts.load('chat-a')
    sessionFacts.activate('chat-b')
    fetchMock.mockResolvedValueOnce({ facts: [fact('fact-b', 'Only chat B')] } as never)
    await expect(sessionFacts.load('chat-b')).resolves.toBe('success')

    oldResponse.resolve({ facts: [fact('fact-a', 'Must not leak from chat A')] })
    await expect(oldLoad).resolves.toBe('discarded')
    expect(sessionFacts.facts.value).toEqual([fact('fact-b', 'Only chat B')])
  })

  it('drops a delayed GET after the scope is cleared for disabled or departed chat', async () => {
    const oldResponse = deferred<{ facts: ReturnType<typeof fact>[] }>()
    fetchMock.mockReturnValueOnce(oldResponse.promise as never)
    const sessionFacts = useSessionFacts()

    sessionFacts.activate('chat-a')
    const oldLoad = sessionFacts.load('chat-a')
    sessionFacts.clear()

    oldResponse.resolve({ facts: [fact('fact-a', 'Must not survive a cleared scope')] })
    await expect(oldLoad).resolves.toBe('discarded')
    expect(sessionFacts.facts.value).toEqual([])
    expect(sessionFacts.available.value).toBe(false)
  })

  it('drops a delayed proposal response and does not re-read the previous chat', async () => {
    vi.stubGlobal('document', { cookie: '' })
    const oldProposal = deferred<unknown>()
    fetchMock.mockReturnValueOnce(oldProposal.promise as never)
    const sessionFacts = useSessionFacts()

    sessionFacts.activate('chat-a')
    const proposal = sessionFacts.propose('chat-a', 'message-a', 'GOAL')
    sessionFacts.activate('chat-b')
    fetchMock.mockResolvedValueOnce({ facts: [fact('fact-b', 'Only chat B')] } as never)
    await expect(sessionFacts.load('chat-b')).resolves.toBe('success')

    oldProposal.resolve({ created: true, fact: fact('fact-a', 'Must not leak from chat A') })
    await expect(proposal).resolves.toEqual({ ok: false, discarded: true })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(sessionFacts.facts.value).toEqual([fact('fact-b', 'Only chat B')])
  })
})
