// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SelectionDrawer from '../src/components/chat/SelectionDrawer.vue'

const mocks = vi.hoisted(() => ({
  options: undefined as any, transport: undefined as any, state: undefined as any,
  send: vi.fn(), stop: vi.fn(), fetch: vi.fn(), refresh: vi.fn(), push: vi.fn(), toast: vi.fn()
}))
vi.mock('@ai-sdk/vue', () => ({ Chat: class {
  constructor(options: any) { mocks.options = options }
  get messages() { return mocks.state.messages }
  get status() { return mocks.state.status }
  sendMessage(message: any) { mocks.send(message) }
  stop() { mocks.stop() }
} }))
vi.mock('ai', () => ({ DefaultChatTransport: class { constructor(options: any) { mocks.transport = options } } }))
vi.mock('ofetch', () => ({ $fetch: mocks.fetch }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
vi.mock('@nuxt/ui/composables', () => ({ useToast: () => ({ add: mocks.toast }) }))
vi.mock('../src/composables/useCsrf', () => ({ useCsrf: () => ({ csrf: () => 'csrf', headerName: 'x-csrf-token' }) }))
vi.mock('../src/composables/useChats', () => ({ useChats: () => ({ fetchChats: mocks.refresh }) }))
vi.mock('../src/components/chat/message/MessageContent.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../src/components/chat/message/MessageActions.vue', () => ({ default: { template: '<div />' } }))
const wrappers: ReturnType<typeof mount>[] = []
function render() {
  const wrapper = mount(SelectionDrawer, {
    props: { open: true, selectedText: 'A selected phrase', chatId: 'parent-chat' },
    global: { stubs: {
      UIcon: true, UChatMessages: true,
      UButton: { props: ['label', 'disabled'], template: '<button :disabled="disabled">{{ label }}</button>' }
    } }
  })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => {
  vi.clearAllMocks()
  mocks.state = reactive({ messages: [], status: 'ready' })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('selection conversation', () => {
  it('reuses the server conversation and saves only persisted message IDs', async () => {
    const wrapper = render()
    expect(mocks.transport.body().tempChatId).toBeUndefined()
    expect(wrapper.findAll('button').find(button => button.text() === 'Save')?.attributes('disabled')).toBeDefined()
    mocks.options.onData({ type: 'data-temp-chat', data: { chatId: 'server-temp-chat', messageIds: ['saved-user', 'saved-answer'] } })
    expect(mocks.transport.body().tempChatId).toBe('server-temp-chat')
    mocks.state.messages = [
      { id: 'failed-user', role: 'user', parts: [{ type: 'text', text: 'Earlier failed request' }] },
      { id: 'saved-user', role: 'user', parts: [{ type: 'text', text: 'Untrusted client text' }] },
      { id: 'saved-answer', role: 'assistant', parts: [{ type: 'text', text: 'Untrusted client answer' }] }
    ]
    mocks.fetch.mockResolvedValue({ chat: { id: 'saved-chat' } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === 'Save')!.trigger('click')
    await flushPromises()
    expect(mocks.fetch).toHaveBeenCalledWith('/api/chats/save-standalone', expect.objectContaining({
      body: { sourceChatId: 'server-temp-chat', messages: [{ id: 'saved-user' }, { id: 'saved-answer' }] }
    }))
    expect(mocks.refresh).toHaveBeenCalled()
    expect(mocks.push).toHaveBeenCalledWith('/chat/saved-chat')
  })

  it('supports multiline and IME input, guards duplicate submission, and stops on close', async () => {
    const wrapper = render()
    const input = wrapper.get('textarea')
    await input.setValue('A follow-up question')
    await input.trigger('keydown', { key: 'Enter', shiftKey: true })
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(mocks.send).not.toHaveBeenCalled()
    mocks.state.status = 'submitted'
    await input.trigger('keydown', { key: 'Enter' })
    expect(mocks.send).not.toHaveBeenCalled()
    mocks.state.status = 'ready'
    await input.trigger('keydown', { key: 'Enter' })
    expect(mocks.send).toHaveBeenCalledWith({ text: 'A follow-up question' })
    expect((input.element as HTMLTextAreaElement).value).toBe('')
    await wrapper.setProps({ open: false })
    expect(mocks.stop).toHaveBeenCalled()
  })
})
