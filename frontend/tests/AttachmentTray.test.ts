// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AttachmentTray from '../src/components/chat/AttachmentTray.vue'

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }))
vi.mock('ofetch', () => ({ $fetch: fetchMock }))

class FakeXHR {
  static instances: FakeXHR[] = []
  static autoComplete = true
  upload: { onprogress?: (event: any) => void } = {}
  status = 201
  responseText = ''
  onload?: () => void
  onerror?: () => void
  onabort?: () => void
  headers: Record<string, string> = {}
  url = ''
  body?: File
  constructor() {
    FakeXHR.instances.push(this)
    this.responseText = JSON.stringify({ id: `att_ready_${FakeXHR.instances.length}`, status: 'parsing' })
  }
  open(_method: string, url: string) { this.url = url }
  setRequestHeader(name: string, value: string) { this.headers[name] = value }
  send(body: File) { this.body = body; if (FakeXHR.autoComplete) this.onload?.() }
  abort() { this.onabort?.() }
}

const ButtonStub = defineComponent({
  inheritAttrs: false,
  template: '<button v-bind="$attrs"><slot /></button>',
})

describe('AttachmentTray', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    FakeXHR.instances = []
    FakeXHR.autoComplete = true
    ;(globalThis as any).XMLHttpRequest = FakeXHR
    document.cookie = 'csrf-token=test-csrf'
    fetchMock.mockImplementation((request: unknown) => {
      const url = String(request)
      if (url === '/api/attachments/status') return Promise.resolve({ enabled: true })
      if (url === '/api/attachment-batches') return Promise.resolve({ id: 'atb_one' })
      if (url.startsWith('/api/attachments/att_ready_')) return Promise.resolve({ status: 'ready' })
      return Promise.resolve({})
    })
  })

  it('shares one batch across concurrent files and emits ready attachment ids', async () => {
    const wrapper = mount(AttachmentTray, {
      props: { scope: 'draft' },
      global: { stubs: { UButton: ButtonStub } },
    })
    await flushPromises()
    const input = wrapper.get('input[type="file"]')
    const files = [
      new File(['first'], '报错截图.txt', { type: 'text/plain' }),
      new File(['second'], '制度.txt', { type: 'text/plain' }),
    ]
    Object.defineProperty(input.element, 'files', { configurable: true, value: files })
    await input.trigger('change')
    await flushPromises()

    const batchCalls = fetchMock.mock.calls.filter(call => call[0] === '/api/attachment-batches')
    expect(batchCalls).toHaveLength(1)
    expect(FakeXHR.instances).toHaveLength(2)
    expect(FakeXHR.instances[0].url).toBe('/api/attachment-batches/atb_one/files')
    const encodedName = FakeXHR.instances[0].headers['X-File-Name-B64']
    expect(new TextDecoder().decode(Uint8Array.from(atob(encodedName.replace(/-/g, '+').replace(/_/g, '/')), char => char.charCodeAt(0)))).toBe('报错截图.txt')
    await vi.waitFor(() => {
      expect(wrapper.emitted('change')).toContainEqual([['att_ready_1', 'att_ready_2'], []])
    })
  })

  it('clears attachment ids after a message is sent', async () => {
    const wrapper = mount(AttachmentTray, {
      props: { scope: 'chat', chatId: 'chat-1' },
      global: { stubs: { UButton: ButtonStub } },
    })
    await flushPromises()
    ;(wrapper.vm as any).resetAfterSend()
    expect(wrapper.emitted('change')?.at(-1)).toEqual([[], []])
  })

  it('blocks sending while an attachment is still uploading', async () => {
    FakeXHR.autoComplete = false
    const wrapper = mount(AttachmentTray, {
      props: { scope: 'draft' },
      global: { stubs: { UButton: ButtonStub } },
    })
    await flushPromises()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['pending'], 'pending.txt', { type: 'text/plain' })],
    })
    await input.trigger('change')
    await flushPromises()
    expect((wrapper.vm as any).hasBlockingAttachments()).toBe(true)
  })

  it('does not start an upload removed while batch creation is pending', async () => {
    let resolveBatch!: (value: { id: string }) => void
    fetchMock.mockImplementation((request: unknown) => {
      const url = String(request)
      if (url === '/api/attachments/status') return Promise.resolve({ enabled: true })
      if (url === '/api/attachment-batches') return new Promise(resolve => { resolveBatch = resolve })
      return Promise.resolve({})
    })
    const wrapper = mount(AttachmentTray, {
      props: { scope: 'draft' },
      global: { stubs: { UButton: ButtonStub } },
    })
    await flushPromises()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['cancel'], 'cancel.txt', { type: 'text/plain' })],
    })
    await input.trigger('change')
    await wrapper.findAll('button').at(-1)!.trigger('click')
    resolveBatch({ id: 'atb_late' })
    await flushPromises()
    expect(FakeXHR.instances).toHaveLength(0)
  })

  it('uses the controlled MIME for browser files with an empty type', async () => {
    const wrapper = mount(AttachmentTray, {
      props: { scope: 'draft' },
      global: { stubs: { UButton: ButtonStub } },
    })
    await flushPromises()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['# 制度'], 'policy.md')],
    })
    await input.trigger('change')
    await flushPromises()
    expect(FakeXHR.instances[0].headers['Content-Type']).toBe('text/markdown')
  })
})
