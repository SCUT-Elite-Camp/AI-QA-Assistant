// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { UIMessage } from 'ai'
import HitRateDrawer from '../src/components/chat/HitRateDrawer.vue'

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }))
vi.mock('ofetch', () => ({ $fetch: fetchMock }))
const wrappers: ReturnType<typeof mount>[] = []
const user = (id: string, text = '检查报告') => ({ id, role: 'user', parts: [{ type: 'text', text }] }) as UIMessage
const assistant = (id: string, citations: unknown[] = [], extra: unknown[] = []) => ({
  id, role: 'assistant', parts: [
    { type: 'text', text: '回答' },
    { type: 'tool-rag_search', state: 'output-available', toolCallId: id, input: {}, output: citations },
    ...extra
  ]
}) as UIMessage
function render(messages: UIMessage[] = []) {
  const wrapper = mount(HitRateDrawer, {
    props: { open: true, messages },
    global: { stubs: { UIcon: true } }
  })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => { fetchMock.mockReset(); fetchMock.mockResolvedValue({ indexedDocs: [] }) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('retrieval monitor', () => {
  it('keeps pending turns out of the rate and filters, expands details and closes', async () => {
    const wrapper = render([
      user('q1'), assistant('a1', [{ doc_id: 'doc', chunk_id: 'one', title: '周报', similarity: 0.82, snippet: '核实的片段' }]),
      user('q2', '解释一下'), assistant('a2'), user('q3', '等待完成')
    ])
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('50')
    expect(wrapper.findAll('.turn-card')).toHaveLength(3)
    expect(wrapper.findAll('.turn-title')[0].text()).toBe('等待完成')
    await wrapper.findAll('.filter-group button')[1].trigger('click')
    expect(wrapper.findAll('.turn-card')).toHaveLength(1)
    expect(wrapper.findAll('.filter-group button')[1].attributes('aria-pressed')).toBe('true')
    const trigger = wrapper.get('.turn-trigger')
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.turn-detail').attributes('id')).toBe(trigger.attributes('aria-controls'))
    expect(wrapper.get('.citation-card').text()).toContain('核实的片段')
    expect(wrapper.get('.citation-card').text()).toContain('82%')
    await trigger.trigger('click')
    expect(wrapper.find('.turn-detail').exists()).toBe(false)
    await wrapper.findAll('.filter-group button')[2].trigger('click')
    expect(wrapper.findAll('.turn-card')).toHaveLength(1)
    expect(wrapper.get('.turn-title').text()).toBe('解释一下')
    await wrapper.get('[aria-label="Close retrieval monitor"]').trigger('click')
    expect(wrapper.emitted('update:open')).toEqual([[false]])
  })

  it('does not invent vector scores or document counts when metrics are denied', async () => {
    fetchMock.mockRejectedValue({ statusCode: 403 })
    const wrapper = render([user('q'), assistant('a', [{ doc_id: 'doc', chunk_id: 'one', score: 0.91 }])])
    await flushPromises()
    expect(wrapper.findAll('.similarity-cell strong').map(node => node.text())).toEqual(['—', '—'])
    expect(wrapper.findAll('.footprint dd')[0].text()).toBe('—')
    expect(wrapper.get('.hero-value').text()).toBe('100')
    await wrapper.get('.turn-trigger').trigger('click')
    expect(wrapper.get('.citation-heading strong').text()).toBe('—')
  })

  it('preserves zero cosine and zero indexed docs, ignores non-RAG output and deduplicates chunks', async () => {
    const citation = { doc_id: 'doc', chunk_id: 'one', similarity: 0 }
    const wrapper = render([user('q'), assistant('a', [citation, citation], [
      { type: 'tool-chart', state: 'output-available', toolCallId: 'chart', input: {}, output: [{ title: '图表', doc_id: 'not-evidence' }] }
    ])])
    await flushPromises()
    expect(wrapper.findAll('.similarity-cell strong').map(node => node.text())).toEqual(['0%', '0%'])
    expect(wrapper.findAll('.footprint dd').map(node => node.text())).toEqual(['0', '1', '1'])
    expect(wrapper.get('.hero-side-stat strong').text()).toBe('1')
  })

  it('shows distinct conversation and filter empty states with a true zero progress width', async () => {
    const wrapper = render([])
    expect(wrapper.get('.empty-state').text()).toContain('Ready for your first question')
    expect(wrapper.get('.hero-value').text()).toBe('—')
    expect(wrapper.get('.progress-fill').attributes('style')).toContain('width: 0%')
    await wrapper.setProps({ messages: [user('q'), assistant('a')] })
    await wrapper.findAll('.filter-group button')[1].trigger('click')
    expect(wrapper.get('.empty-state').text()).toContain('No matching turns')
  })

  it('keeps an empty assistant placeholder pending until an answer arrives', async () => {
    const placeholder = { id: 'a', role: 'assistant', parts: [] } as UIMessage
    const wrapper = render([user('q'), placeholder])
    expect(wrapper.get('.hero-value').text()).toBe('—')
    expect(wrapper.get('.turn-status').text()).toBe('Pending')
    await wrapper.setProps({ messages: [user('q'), assistant('a')] })
    expect(wrapper.get('.hero-value').text()).toBe('0')
    expect(wrapper.get('.turn-status').text()).toBe('Uncited')
  })
})
