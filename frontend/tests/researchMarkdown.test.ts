import { describe, expect, it } from 'vitest'
import { parse } from '@comark/vue/parse'
import { formatResearchCitations, researchConversationText } from '../src/utils/researchMarkdown'

describe('research citation rendering', () => {
  it('restores the complete long conversation body while supporting legacy events', () => {
    const content = 'A grounded answer with citations [1]. '.repeat(30)
    expect(researchConversationText({ message: content.slice(0, 500), payload: { content } })).toBe(content)
    expect(researchConversationText({ message: 'Legacy answer [1].', payload: {} })).toBe('Legacy answer [1].')
    expect(researchConversationText({ message: 'Summary', payload: { content: true } })).toBe('Summary')
  })
  it('keeps adjacent citations and following sentences outside citation components', async () => {
    const result = await parse(formatResearchCitations('Compare sources [2][3]. Both sprints completed.'))
    const paragraph = result.nodes[0] as any[]
    const citations = paragraph.filter(Array.isArray)
    expect(citations).toHaveLength(2)
    expect(citations.every(node => node[0] === 'cite-mark' && node.length === 2)).toBe(true)
    expect(paragraph.filter(value => typeof value === 'string').join('')).toContain('Both sprints completed.')
  })

  it('retains prose and citations in table cells', async () => {
    const result = await parse(formatResearchCitations('| Metric | Value |\n| --- | --- |\n| Commits | 9 [2] confirmed |'))
    expect(JSON.stringify(result.nodes)).toContain('confirmed')
    expect(JSON.stringify(result.nodes)).toContain('cite-mark')
    expect(JSON.stringify(result.nodes)).not.toContain('</cite-mark>')
  })
})
