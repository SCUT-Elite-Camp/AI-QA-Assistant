// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MessageContent from '../src/components/chat/message/MessageContent.vue'
import { h, Suspense } from 'vue'

vi.mock('../src/components/chat/ModalDocumentViewer.vue', () => ({ default: {
  props: ['open', 'doc'], template: '<div v-if="open" data-reader>{{ doc?.title }}</div>',
} }))

const claim = { claim_id: 'claim_1', text: 'Alpha is complete.', start: 0, end: 18,
  supports: [{ citation_id: 1, quote: 'Alpha completed July 30' }, { citation_id: 2, quote: 'Alpha was completed' }] }
function render(claims = [claim]) {
  const props = { editing: false, message: { id: 'saved-message', role: 'assistant' as const, parts: [
      { type: 'text', text: 'Alpha is complete.[1][2]' },
      { type: 'data-answer-claims', data: claims },
      { type: 'tool-rag_search', state: 'output-available', toolCallId: 'sources', input: {}, output: [
        { index: 1, doc_id: 'a', chunk_id: 'a1', title: 'Project status', chunk_text: 'Alpha completed July 30' },
        { index: 2, doc_id: 'b', chunk_id: 'b1', title: 'Release notes', chunk_text: 'Alpha was completed' },
      ] },
    ] as any[] } }
  return mount({ render: () => h(Suspense, {}, { default: () => h(MessageContent, props) }) }, {
    global: { stubs: {
      UModal: { props: ['open'], template: '<div v-if="open" role="dialog"><slot name="body" /></div>' },
      UButton: { template: '<button><slot /></button>' }, UIcon: true,
    } },
  })
}
describe('answer claim interaction', () => {
  it('underlines only bound prose, opens every quote and document title, and routes source opening to Reader', async () => {
    const wrapper = render()
    await vi.waitFor(() => expect(wrapper.find('span.answer-claim').exists()).toBe(true))
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    const trigger = wrapper.get('span.answer-claim')
    expect(trigger.text()).toBe('Alpha is complete.')
    expect(wrapper.find('.cite-badge-btn').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('[1]')
    await trigger.trigger('click')
    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.text()).toContain('Project status')
    expect(dialog.text()).toContain('Release notes')
    expect(dialog.findAll('blockquote').map(item => item.text())).toEqual(['Alpha completed July 30', 'Alpha was completed'])
    await dialog.get('button').trigger('click')
    expect(wrapper.get('[data-reader]').text()).toBe('Project status')
    wrapper.unmount()
  })
  it('supports keyboard activation on saved messages and does not annotate old or malformed messages', async () => {
    const wrapper = render()
    await vi.waitFor(() => expect(wrapper.find('span.answer-claim').exists()).toBe(true))
    await wrapper.get('span.answer-claim').trigger('keydown.enter')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    wrapper.unmount()
    const old = render([])
    await vi.waitFor(() => expect(old.text()).toContain('Alpha is complete.'))
    expect(old.find('span.answer-claim').exists()).toBe(false)
    expect(old.find('.cite-badge-btn').exists()).toBe(true)
    old.unmount()
    const bad = render([{ ...claim, text: 'Forged body' }])
    await vi.waitFor(() => expect(bad.text()).toContain('Alpha is complete.'))
    expect(bad.find('span.answer-claim').exists()).toBe(false)
    bad.unmount()
  })
})
