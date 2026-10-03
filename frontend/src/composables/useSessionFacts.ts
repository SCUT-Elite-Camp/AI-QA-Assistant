import { computed, ref } from 'vue'
import { $fetch } from 'ofetch'
import { useCsrf } from './useCsrf'
import type {
  FactCategory,
  FactListResponse,
  FactMutationResponse,
  FactProposalResponse,
  FactView,
  SessionFactsResult,
} from '../types/memory'

type LoadResult = 'success' | 'unavailable' | 'failed' | 'discarded'

interface ChatScope {
  chatId: string
  version: number
}

function errorStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined
  const candidate = error as { statusCode?: unknown, response?: { status?: unknown } }
  if (typeof candidate.statusCode === 'number') return candidate.statusCode
  return typeof candidate.response?.status === 'number' ? candidate.response.status : undefined
}

function errorCode(error: unknown): string | undefined {
  if (!error || typeof error !== 'object') return undefined
  const candidate = error as { data?: { code?: unknown } }
  return typeof candidate.data?.code === 'string' ? candidate.data.code : undefined
}

function isUnavailable(error: unknown): boolean {
  const code = errorCode(error)
  return errorStatus(error) === 404 || code === 'session_fact_disabled'
}

/**
 * In-memory-only client state for one currently visible, authenticated chat.
 * The server remains the source of truth: all successful mutations re-read GET.
 */
export function useSessionFacts() {
  const { csrf, headerName } = useCsrf()
  const facts = ref<FactView[]>([])
  const available = ref(false)
  const loading = ref(false)
  const pendingIds = ref<string[]>([])
  let activeChatId: string | null = null
  let scopeVersion = 0

  const proposedFacts = computed(() => facts.value.filter(fact => fact.status === 'PROPOSED'))
  const confirmedFacts = computed(() => facts.value.filter(fact => (
    fact.status === 'CONFIRMED'
    && (!fact.expiresAt || new Date(fact.expiresAt).getTime() > Date.now())
  )))

  function resetVisibleState() {
    facts.value = []
    available.value = false
    loading.value = false
    pendingIds.value = []
  }

  function activate(chatId: string) {
    scopeVersion += 1
    activeChatId = chatId || null
    resetVisibleState()
  }

  function clear() {
    scopeVersion += 1
    activeChatId = null
    resetVisibleState()
  }

  function captureScope(chatId: string): ChatScope | null {
    if (!chatId || activeChatId !== chatId) return null
    return { chatId, version: scopeVersion }
  }

  function isCurrent(scope: ChatScope): boolean {
    return activeChatId === scope.chatId && scopeVersion === scope.version
  }

  function isPending(id: string) {
    return pendingIds.value.includes(id)
  }

  function setPending(id: string, pending: boolean) {
    pendingIds.value = pending
      ? [...new Set([...pendingIds.value, id])]
      : pendingIds.value.filter(candidate => candidate !== id)
  }

  async function load(chatId: string, expectedScope = captureScope(chatId)): Promise<LoadResult> {
    if (!expectedScope || !isCurrent(expectedScope)) return 'discarded'

    loading.value = true
    try {
      const response = await $fetch<FactListResponse>(`/api/chats/${chatId}/memory/facts`)
      if (!isCurrent(expectedScope)) return 'discarded'
      facts.value = response.facts
      available.value = true
      return 'success'
    } catch (error) {
      if (!isCurrent(expectedScope)) return 'discarded'
      if (isUnavailable(error)) {
        clear()
        return 'unavailable'
      }
      // Keep the last successful result visible for transient failures.
      return 'failed'
    } finally {
      if (isCurrent(expectedScope)) loading.value = false
    }
  }

  async function propose(chatId: string, sourceMessageId: string, category: FactCategory): Promise<SessionFactsResult> {
    const scope = captureScope(chatId)
    if (!scope) return { ok: false, discarded: true }
    if (isPending(sourceMessageId)) return { ok: false, code: 'operation_failed' }
    setPending(sourceMessageId, true)
    try {
      await $fetch<FactProposalResponse>(`/api/chats/${chatId}/memory/facts/proposals`, {
        method: 'POST',
        headers: { [headerName]: csrf() },
        body: { source_message_id: sourceMessageId, category }
      })
      if (!isCurrent(scope)) return { ok: false, discarded: true }
      const result = await load(chatId, scope)
      if (result === 'discarded') return { ok: false, discarded: true }
      return result === 'success' ? { ok: true } : { ok: false, code: 'operation_failed' }
    } catch (error) {
      if (!isCurrent(scope)) return { ok: false, discarded: true }
      return { ok: false, code: errorCode(error) === 'fact_sensitive' ? 'fact_sensitive' : 'operation_failed' }
    } finally {
      if (isCurrent(scope)) setPending(sourceMessageId, false)
    }
  }

  async function mutate(chatId: string, factId: string, action: 'confirm' | 'revoke'): Promise<SessionFactsResult> {
    const scope = captureScope(chatId)
    if (!scope) return { ok: false, discarded: true }
    if (isPending(factId)) return { ok: false, code: 'operation_failed' }
    setPending(factId, true)
    try {
      await $fetch<FactMutationResponse>(`/api/chats/${chatId}/memory/facts/${factId}/${action}`, {
        method: 'POST',
        headers: { [headerName]: csrf() }
      })
      if (!isCurrent(scope)) return { ok: false, discarded: true }
      const result = await load(chatId, scope)
      if (result === 'discarded') return { ok: false, discarded: true }
      return result === 'success' ? { ok: true } : { ok: false, code: 'operation_failed' }
    } catch {
      if (!isCurrent(scope)) return { ok: false, discarded: true }
      // Re-read even after a rejected mutation so no optimistic state survives.
      const result = await load(chatId, scope)
      if (result === 'discarded') return { ok: false, discarded: true }
      return { ok: false, code: 'operation_failed' }
    } finally {
      if (isCurrent(scope)) setPending(factId, false)
    }
  }

  return {
    facts,
    proposedFacts,
    confirmedFacts,
    available,
    loading,
    activate,
    clear,
    isPending,
    load,
    propose,
    confirm: (chatId: string, factId: string) => mutate(chatId, factId, 'confirm'),
    revoke: (chatId: string, factId: string) => mutate(chatId, factId, 'revoke')
  }
}
