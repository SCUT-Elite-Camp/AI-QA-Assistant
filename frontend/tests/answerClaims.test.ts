import { describe, expect, it } from 'vitest'
import { parse } from 'comark'
import { parseAnswerClaims } from '../shared/answerClaims'
import { createAnswerClaimMarkup } from '../src/utils/answerClaimMarkup'
import { formatResearchCitations } from '../src/utils/researchMarkdown'

const sources = [{ citation_id: 1, snippet: 'Alpha completed July 30', title: 'Project status' }]
function annotation(answer: string, text = answer) {
  const start = Array.from(answer.slice(0, answer.indexOf(text))).length
  return { claim_id: 'claim_1', text, start, end: start + Array.from(text).length,
    supports: [{ citation_id: 1, quote: 'Alpha completed July 30' }] }
}
describe('display claim contract', () => {
  it('validates exact final body offsets and original quotes', () => {
    const body = 'Alpha is complete.[1]'
    expect(parseAnswerClaims([annotation(body, 'Alpha is complete.')], body, sources)).toHaveLength(1)
    expect(() => parseAnswerClaims([annotation(body, 'Different')], body, sources)).toThrow()
    expect(() => parseAnswerClaims([{ ...annotation(body), supports: [{ citation_id: 1, quote: 'fabricated' }] }], body, sources)).toThrow()
    expect(() => parseAnswerClaims([{ ...annotation(body), supports: [{ citation_id: 2, quote: 'Alpha' }] }], body, sources)).toThrow()
  })
  it('supports Unicode code point offsets and rejects overlap', () => {
    const body = '😀 Alpha'
    expect(parseAnswerClaims([annotation(body, 'Alpha')], body, sources)[0]?.start).toBe(2)
    expect(() => parseAnswerClaims([annotation(body), annotation(body)], body, sources)).toThrow()
  })
  it('does not accept verification internals in the display contract', () => {
    expect(() => parseAnswerClaims([{ ...annotation('Alpha'), verdict: 'supported' }], 'Alpha', sources)).toThrow()
  })
})

describe('claim Markdown rendering', () => {
  it('leaves introductions, bullet labels and spacing outside the clickable assertions', async () => {
    const body = 'Here are the details:\n\n- Owner: Jiaxing Dai completed Fusion.\n- Date: Fusion completed July 30.'
    const claims = [annotation(body, 'Jiaxing Dai completed Fusion.'), { ...annotation(body, 'Fusion completed July 30.'), claim_id: 'claim_2' }]
    const tree = await parse(body, { plugins: [createAnswerClaimMarkup(() => body, () => claims)] })
    function marked(nodes: any[]): string[] {
      return nodes.flatMap(node => typeof node === 'string' ? []
        : node[0] === 'answer-claim' ? [node.slice(2).join('')] : marked(node.slice(2)))
    }
    expect(marked(tree.nodes)).toEqual(['Jiaxing Dai completed Fusion.', 'Fusion completed July 30.'])
    expect(JSON.stringify(tree.nodes)).toContain('Owner: ')
    expect(JSON.stringify(tree.nodes)).toContain('Date: ')
    expect(tree.nodes.some(node => typeof node !== 'string' && node[0] === 'ul')).toBe(true)
  })
  it.each([
    'Alpha is complete.',
    '**Alpha** is complete.',
    '## Alpha is complete.',
    '- Alpha is complete.\n- A second point.',
    '| State |\n| --- |\n| Alpha is complete. |',
    'Alpha uses `three` queries.',
    '[Alpha](https://example.test) is complete.',
    'Alpha &amp; Beta are complete.',
  ])('preserves Markdown structure while decorating %s', async (body) => {
    const claims = [annotation(body)]
    const plugin = createAnswerClaimMarkup(() => body, () => claims)
    const original = await parse(body)
    const decorated = await parse(body, { plugins: [plugin] })
    expect(JSON.stringify(decorated.nodes)).toContain('answer-claim')
    expect(decorated.nodes[0]?.[0]).toEqual(original.nodes[0]?.[0])
  })
  it('keeps source citations separate and handles repeated body occurrences', async () => {
    const body = 'Alpha.[1] Alpha.[1]'
    const claims = [annotation(body, 'Alpha.'), { ...annotation(body, 'Alpha.'), start: 10, end: 16 }]
    const tree = await parse(formatResearchCitations(body), { plugins: [createAnswerClaimMarkup(() => body, () => claims)] })
    expect(JSON.stringify(tree.nodes)).toContain('cite-mark')
    expect(JSON.stringify(tree.nodes).match(/answer-claim/g)).toHaveLength(2)
  })
  it('hides known citation badges without moving the saved claim binding or changing literal code', async () => {
    const body = 'Alpha.[1] Alpha.[1]'
    const claims = [annotation(body, 'Alpha.'), { ...annotation(body, 'Alpha.'), start: 10, end: 16 }]
    const markdown = formatResearchCitations(body, new Set([1]), false)
    expect(markdown).toBe('Alpha. Alpha.')
    const tree = await parse(markdown, { plugins: [createAnswerClaimMarkup(() => body, () => claims)] })
    expect(JSON.stringify(tree.nodes)).not.toContain('cite-mark')
    expect(JSON.stringify(tree.nodes).match(/answer-claim/g)).toHaveLength(2)
    expect(formatResearchCitations('Use `items[1]`.[1] Keep [2].', new Set([1]), false)).toBe('Use `items[1]`. Keep [2].')
  })
})
