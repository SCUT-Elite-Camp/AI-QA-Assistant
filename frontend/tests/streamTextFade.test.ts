// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { ComarkNode, ComarkParsePostState } from '@comark/vue'
import { createStreamTextFade } from '../src/utils/streamTextFade'
import StreamGlyph from '../src/components/chat/StreamGlyph'

function state(nodes: ComarkNode[]): ComarkParsePostState {
  return { markdown: '', tree: { nodes, frontmatter: {}, meta: {} }, options: {}, tokens: [] }
}
function glyphs(nodes: ComarkNode[]): Record<string, unknown>[] {
  return nodes.flatMap(node => typeof node === 'string' || node[0] === null ? []
    : node[0] === 'stream-glyph' ? [node[1]] : glyphs(node.slice(2) as ComarkNode[]))
}
afterEach(() => vi.useRealTimers())

describe('streamed text contrast fade', () => {
  it('leaves existing history completely undecorated', () => {
    const input = state([['p', {}, 'History']])
    createStreamTextFade(() => false).post!(input)
    expect(input.tree.nodes).toEqual([['p', {}, 'History']])
  })

  it('preserves each character birth time as new text arrives, including across inline Markdown', () => {
    let time = 1000
    const fade = createStreamTextFade(() => true, () => time)
    const first = state([['p', {}, '你', ['strong', {}, '好']]])
    fade.post!(first)
    time = 1080
    const next = state([['p', {}, '你', ['strong', {}, '好呀']]])
    fade.post!(next)
    expect(glyphs(next.tree.nodes).map(value => [value.text, value.born])).toEqual([
      ['你', 1000], ['好', 1000], ['呀', 1080],
    ])
    expect(next.tree.nodes[0]?.[0]).toBe('p')
  })

  it('removes aged wrappers and never nests spans when Comark reuses parsed blocks', () => {
    let time = 1000
    const fade = createStreamTextFade(() => true, () => time)
    const input = state([['p', {}, 'Stable']])
    fade.post!(input)
    time = 1500
    input.tree.nodes.push(['p', {}, 'New'])
    fade.post!(input)
    expect(input.tree.nodes[0]).toEqual(['p', {}, 'Stable'])
    expect(glyphs(input.tree.nodes).map(value => value.text)).toEqual(['N', 'e', 'w'])
  })

  it('preserves citation widgets and syntax highlighting, and keeps Unicode graphemes intact', () => {
    const code: ComarkNode = ['pre', {}, ['code', {}, 'print(1)']]
    const cite: ComarkNode = ['cite-mark', { index: 1 }, '1']
    const input = state([['p', {}, 'e\u0301👨‍👩‍👧‍👦', cite], code])
    createStreamTextFade(() => true, () => 1000).post!(input)
    expect(glyphs(input.tree.nodes).map(value => value.text)).toEqual(['e\u0301', '👨‍👩‍👧‍👦'])
    expect(input.tree.nodes[1]).toEqual(code)
    expect(JSON.stringify(input.tree.nodes)).toContain(JSON.stringify(cite))
  })

  it('bounds animated DOM nodes for long bursts', () => {
    const input = state([['p', {}, '字'.repeat(2000)]])
    createStreamTextFade(() => true, () => 1000).post!(input)
    expect(glyphs(input.tree.nodes)).toHaveLength(96)
  })

  it('lets the final characters finish fading after streaming ends', () => {
    let streaming = true
    let time = 1000
    const fade = createStreamTextFade(() => streaming, () => time)
    fade.post!(state([['p', {}, 'End']]))
    streaming = false
    time = 1100
    const final = state([['p', {}, 'End!']])
    fade.post!(final)
    expect(glyphs(final.tree.nodes).map(value => value.born)).toEqual([1000, 1000, 1000, 1100])
  })

  it('renders escaped text and does not restart a glyph animation on an unrelated offset update', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(1100)
    const wrapper = mount(StreamGlyph, { props: { text: '<', born: 1000, offset: 0 } })
    expect(wrapper.text()).toBe('<')
    expect(wrapper.html()).toContain('&lt;')
    expect(wrapper.attributes('style')).toContain('animation-delay: -100ms')
    vi.setSystemTime(1200)
    await wrapper.setProps({ offset: 1 })
    expect(wrapper.attributes('style')).toContain('animation-delay: -100ms')
    await wrapper.setProps({ born: 1200, text: '好' })
    expect(wrapper.attributes('style')).toContain('animation-delay: 0ms')
    wrapper.unmount()
  })
})
