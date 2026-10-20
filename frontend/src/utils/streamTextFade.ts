/// <reference lib="es2022.intl" />
import type { ComarkNode, ComarkPlugin } from '@comark/vue'

export const STREAM_FADE_MS = 420
const skipTags = new Set(['pre', 'code', 'script', 'style', 'cite-mark', 'source-link', 'answer-claim'])

/** One instance per message renderer; only recently revealed prose is decorated. */
export function createStreamTextFade(streaming: () => boolean, now = () => Date.now()): ComarkPlugin {
  const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  let previous: string[] = []
  let births: number[] = []
  let started = false
  const split = (text: string) => Array.from(segmenter.segment(text), part => part.segment)

  function compact(nodes: ComarkNode[]): ComarkNode[] {
    const result: ComarkNode[] = []
    for (const node of nodes) {
      const last = result[result.length - 1]
      if (typeof node === 'string' && typeof last === 'string') result[result.length - 1] = last + node
      else result.push(node)
    }
    return result
  }

  function clean(node: ComarkNode): ComarkNode {
    if (typeof node === 'string' || node[0] === null) return node
    if (node[0] === 'stream-glyph') return String(node[1].text ?? '')
    return [node[0], node[1], ...compact(node.slice(2).map(child => clean(child as ComarkNode)))]
  }

  return {
    name: 'stream-text-fade',
    post(state) {
      if (!streaming() && !started) return // History never fades in on load.
      started = true
      const nodes = state.tree.nodes.map(clean)
      const characters: string[] = []
      function collect(node: ComarkNode) {
        if (typeof node === 'string') characters.push(...split(node))
        else if (node[0] !== null && !skipTags.has(node[0])) {
          node.slice(2).forEach(child => collect(child as ComarkNode))
        }
      }
      nodes.forEach(collect)
      let common = 0
      while (common < previous.length && previous[common] === characters[common]) common++
      const time = now()
      births = [...births.slice(0, common), ...characters.slice(common).map(() => time)]
      previous = characters
      let offset = 0
      function decorate(node: ComarkNode): ComarkNode[] {
        if (typeof node === 'string') {
          const result: ComarkNode[] = []
          let stable = ''
          for (const text of split(node)) {
            const index = offset++
            const born = births[index]!
            if (time - born < STREAM_FADE_MS && index >= characters.length - 96) {
              if (stable) { result.push(stable); stable = '' }
              result.push(['stream-glyph', { text, born, offset: index }])
            } else stable += text
          }
          if (stable) result.push(stable)
          return result
        }
        if (node[0] === null || skipTags.has(node[0])) return [node]
        return [[node[0], node[1], ...node.slice(2).flatMap(child => decorate(child as ComarkNode))]]
      }
      state.tree.nodes = nodes.flatMap(decorate)
    }
  }
}
