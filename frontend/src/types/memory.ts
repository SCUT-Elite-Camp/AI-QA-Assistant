export const FACT_CATEGORIES = ['GOAL', 'PREFERENCE', 'PLAN_CONSTRAINT'] as const

export type FactCategory = typeof FACT_CATEGORIES[number]
export type FactStatus = 'PROPOSED' | 'CONFIRMED' | 'REVOKED'

/**
 * The browser-safe Fact projection returned by the four 09-Web endpoints.
 * It intentionally has no user, chat, revision, proposal-key, or source body.
 */
export interface FactView {
  id: string
  category: FactCategory
  status: FactStatus
  value: string
  sourceMessageId: string | null
  expiresAt: string | null
  confirmedAt: string | null
  createdAt: string
}

export interface FactListResponse {
  facts: FactView[]
}

export interface FactMutationResponse {
  fact: FactView
}

export interface FactProposalResponse extends FactMutationResponse {
  created: boolean
}

export type SessionFactsResult =
  | { ok: true }
  | { ok: false, code?: 'fact_sensitive' | 'operation_failed' }
  | { ok: false, discarded: true }
