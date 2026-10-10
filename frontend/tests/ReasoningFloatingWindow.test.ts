// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReasoningFloatingWindow from '../src/components/chat/ReasoningFloatingWindow.vue'
vi.mock('../src/components/chat/Comark', () => ({ default: { template: '<div />' } }))
vi.mock('../src/components/chat/tool/Sources.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../src/components/chat/ModalDocumentViewer.vue', () => ({ default: { template: '<div />' } }))
const message = (parts: any[]) => ({ id: 'reasoning-test', role: 'assistant' as const, parts })
const search = { type: 'tool-rag_search', toolCallId: 'search', state: 'input-available', input: { query: 'test' } }
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers() })
describe('Reasoning floating window', () => {
  it('keeps the compact current step through streaming and completion, and restores history', async () => {
    vi.useFakeTimers()
    const wrapper = mount(ReasoningFloatingWindow, { props: { message: message([search]), status: 'submitted' }, global: { stubs: { UIcon: true } } })
    await wrapper.get('button[aria-expanded]').trigger('click')
    expect(wrapper.get('button[aria-expanded]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.text()).toContain('Searching knowledge base')
    await wrapper.setProps({ status: 'streaming' })
    expect(wrapper.get('button[aria-expanded]').attributes('aria-expanded')).toBe('false')
    await wrapper.setProps({ message: message([search, { type: 'reasoning', state: 'streaming', text: 'Checking evidence' }]) })
    expect(wrapper.text()).not.toContain('Searching knowledge base')
    await wrapper.setProps({ message: message([search, { type: 'text', state: 'streaming', text: 'Answer' }]) })
    const activeLabel = wrapper.text()
    await wrapper.setProps({ status: 'ready', message: message([search, { type: 'text', state: 'done', text: 'Answer' }]) })
    expect(wrapper.get('button[aria-expanded]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.text()).not.toBe(activeLabel)
    await wrapper.get('button[aria-expanded]').trigger('click')
    expect(wrapper.text()).toContain('实时推理过程')
    expect(wrapper.text()).toContain('Knowledge base searched')
    wrapper.unmount()
  })
  it('allows completed history to collapse and remains closed when dismissed', async () => {
    const wrapper = mount(ReasoningFloatingWindow, { props: { message: message([{ type: 'reasoning', state: 'done', text: 'Checked' }]), status: 'ready' }, global: { stubs: { UIcon: true } } })
    await wrapper.get('button[aria-expanded]').trigger('click')
    expect(wrapper.get('button[aria-expanded]').attributes('aria-expanded')).toBe('false')
    await wrapper.get('button[title="关闭小窗"]').trigger('click')
    expect(wrapper.find('button[aria-expanded]').exists()).toBe(false)
    wrapper.unmount()
  })
})
