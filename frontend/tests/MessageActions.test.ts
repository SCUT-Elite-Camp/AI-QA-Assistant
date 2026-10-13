// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MessageActions from '../src/components/chat/message/MessageActions.vue'

vi.mock('@vueuse/core', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))

function render(parts: any[] = [{ type: 'text', text: 'Answer' }]) {
  return mount(MessageActions, {
    props: { message: { id: 'answer', role: 'assistant', parts }, streaming: false, editing: false, vote: null },
    global: { stubs: {
      UTooltip: { template: '<span><slot /></span>' },
      UButton: { props: ['color'], template: '<button :data-color="color"><slot /></button>' },
    } },
  })
}

describe('response actions', () => {
  it('changes Favorite only after the parent confirms the saved state', async () => {
    const wrapper = render()
    const favorite = wrapper.get('[aria-label="Favorite response"]')
    await favorite.trigger('click')
    expect(wrapper.emitted('favorite')?.[0]?.[1]).toBe(true)
    expect(favorite.attributes('data-color')).toBe('neutral')
    await wrapper.setProps({ message: { ...wrapper.props('message'), isFavorite: true } })
    expect(favorite.attributes('data-color')).toBe('warning')
    wrapper.unmount()
  })

  it('offers copy and retry for transient failures without saving or voting', () => {
    const wrapper = render([{ type: 'text', text: 'Model unavailable' },
      { type: 'data-answer-status', data: { persisted: false, status: 'model_unavailable' } }])
    expect(wrapper.find('[aria-label="Favorite response"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Good response"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Bad response"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Copy response"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="Regenerate response"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
