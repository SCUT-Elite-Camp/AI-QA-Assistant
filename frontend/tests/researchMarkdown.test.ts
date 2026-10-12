import { describe, expect, it } from 'vitest'
import { parse } from '@comark/vue/parse'
import { formatResearchCitations, researchConversationText } from '../src/utils/researchMarkdown'

describe('research citation rendering', () => {
  it('preserves code in an unfinished live fence and transforms later prose after closure', () => {
    const partial = 'Claim [1].\n```python\nitems = [1, 2]\nprint(items[1])'
    const rendered = formatResearchCitations(partial, new Set([1, 2]))
    expect(rendered.match(/cite-mark/g)).toHaveLength(1)
    expect(rendered).toContain('items = [1, 2]')
    expect(rendered).toContain('print(items[1])')
    expect(formatResearchCitations(partial + '\n```\nNext claim [2].').match(/cite-mark/g)).toHaveLength(2)
  })

  it('leaves numeric brackets without matching saved evidence unchanged', () => {
    expect(formatResearchCitations('Values [1, 2] and source [3].', new Set([3])))
      .toBe('Values [1, 2] and source  :cite-mark{index="3"} .')
    expect(formatResearchCitations('items[1]', new Set())).toBe('items[1]')
  })

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

  it('renders grouped fast-answer markers and leaves code examples alone', async () => {
    const result = await parse(formatResearchCitations('Claims [1, 2,4,5]. `sample [9]`'))
    const rendered = JSON.stringify(result.nodes)
    expect(rendered.match(/cite-mark/g)).toHaveLength(4)
    expect(rendered).toContain('sample [9]')
  })
})
