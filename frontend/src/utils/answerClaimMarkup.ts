import { parse } from 'comark'
import type { ComarkNode, ComarkPlugin } from '@comark/vue'
import type { AnswerClaim } from '../../shared/answerClaims'

const hidden = new Set(['cite-mark', 'source-link', 'script', 'style'])
const canonical = (value: string) => value.replace(/\[\d+\]/g, '').replace(/\s/gu, '')
function visible(nodes: ComarkNode[]): string {
  return nodes.map(node => typeof node === 'string' ? node
    : node[0] === null || hidden.has(node[0]) ? '' : visible(node.slice(2) as ComarkNode[])).join('')
}

/** Decorate parsed text nodes, preserving Markdown structure and escaping. */
export function createAnswerClaimMarkup(source: () => string, claims: () => AnswerClaim[]): ComarkPlugin {
  return {
    name: 'answer-claim-bindings',
    async post(state) {
      const annotations = claims()
      if (!annotations.length) return
      const raw = source()
      const chars = Array.from(raw)
      const full = canonical(visible(state.tree.nodes))
      const ranges: { start: number, end: number, id: string }[] = []
      for (const claim of annotations) {
        if (chars.slice(claim.start, claim.end).join('') !== claim.text) return
        const prefixTree = await parse(chars.slice(0, claim.start).join('').replace(/\[\d+\]/g, ''))
        const claimTree = await parse(claim.text.replace(/\[\d+\]/g, ''))
        let prefix = canonical(visible(prefixTree.nodes))
        // An unfinished Markdown delimiter in a prefix is syntax in the full body.
        while (!full.startsWith(prefix) && /[*_#`>\-\\\[(!]$/.test(prefix)) prefix = prefix.slice(0, -1)
        const text = canonical(visible(claimTree.nodes))
        if (!full.startsWith(prefix) || full.slice(prefix.length, prefix.length + text.length) !== text) return
        if (text) ranges.push({ start: prefix.length, end: prefix.length + text.length, id: claim.claim_id })
      }
      let cursor = 0
      function decorate(node: ComarkNode): ComarkNode[] {
        if (typeof node !== 'string') {
          if (node[0] === null || hidden.has(node[0])) return [node]
          // Model-authored directives cannot impersonate our display controls.
          const tag = node[0] === 'answer-claim' ? 'span' : node[0]
          return [[tag, node[0] === 'answer-claim' ? {} : node[1],
            ...node.slice(2).flatMap(child => decorate(child as ComarkNode))]]
        }
        const segments: { id?: string, text: string }[] = []
        // Numeric markers are citation widgets, even when formatting leaves one literal.
        for (const piece of node.split(/(\[\d+\])/g)) {
          if (/^\[\d+\]$/.test(piece)) { segments.push({ text: piece }); continue }
          for (const char of piece) {
            // Inter-claim whitespace belongs to layout, not the next assertion.
            const range = ranges.find(item => (/\s/u.test(char) ? item.start < cursor : item.start <= cursor) && cursor < item.end)
            const id = range?.id
            const last = segments[segments.length - 1]
            if (last && last.id === id) last.text += char
            else segments.push({ id, text: char })
            if (!/\s/u.test(char)) cursor++
          }
        }
        return segments.map(segment => segment.id
          ? ['answer-claim', { 'claim-id': segment.id }, segment.text] : segment.text)
      }
      state.tree.nodes = state.tree.nodes.flatMap(decorate)
    },
  }
}
