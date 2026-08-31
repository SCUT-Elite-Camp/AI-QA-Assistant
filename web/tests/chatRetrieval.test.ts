import { describe, expect, it } from 'vitest'
import { knowledgeBaseRetrievalEnabled } from '../shared/utils/chatRetrieval'

describe('knowledge-base retrieval metadata', () => {
  it('defaults to enterprise knowledge-base retrieval', () => {
    expect(knowledgeBaseRetrievalEnabled(undefined)).toBe(true)
    expect(knowledgeBaseRetrievalEnabled({})).toBe(true)
  })

  it('only disables retrieval for an explicit false value', () => {
    expect(knowledgeBaseRetrievalEnabled({ knowledgeBaseRetrievalEnabled: false })).toBe(false)
    expect(knowledgeBaseRetrievalEnabled({ knowledgeBaseRetrievalEnabled: 'false' })).toBe(true)
  })

  it('restores the preference from a persisted first-message data part', () => {
    expect(knowledgeBaseRetrievalEnabled(undefined, [
      {
        type: 'data-chat-preferences',
        data: { knowledge_base_retrieval_enabled: false },
      },
    ])).toBe(false)
  })
})
