import { describe, expect, it } from 'vitest'
import { knowledgeBaseRetrievalEnabled, retrievalSourceSelection } from '../shared/utils/chatRetrieval'

describe('knowledge-base retrieval metadata', () => {
  it('preserves explicit source selection without treating availability as a selection', () => {
    expect(retrievalSourceSelection(undefined)).toBeUndefined()
    expect(retrievalSourceSelection({ retrievalSources: ['personal_library'] })).toEqual(['personal_library'])
    expect(retrievalSourceSelection({ retrievalSources: [] })).toEqual([])
    expect(retrievalSourceSelection(undefined, [{ type: 'data-chat-preferences', data: { retrieval_sources: ['enterprise_kb'] } }]))
      .toEqual(['enterprise_kb'])
  })
  it('rejects unknown source namespaces instead of silently broadening a selection', () => {
    expect(() => retrievalSourceSelection({ retrievalSources: ['other-user'] })).toThrow('invalid_retrieval_sources')
  })
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
