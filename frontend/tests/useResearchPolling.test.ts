// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useResearchPolling } from '../src/composables/useResearchPolling'
import type { ResearchSnapshot } from '../src/types/research'

const snapshot = (status: string): ResearchSnapshot => ({
  job: { status }, progress: {}, events: { events: [], next_after_event_id: 0 },
}) as ResearchSnapshot

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('research snapshot polling', () => {
  it('shows an already completed report and stops polling', async () => {
    const fetch = vi.fn().mockResolvedValue(snapshot('completed'))
    let polling!: ReturnType<typeof useResearchPolling>
    const wrapper = mount(defineComponent({ setup() { polling = useResearchPolling(fetch); return () => null } }))
    await flushPromises()
    expect(polling.job.value?.status).toBe('completed')
    expect(polling.loading.value).toBe(false)
    await vi.advanceTimersByTimeAsync(15000)
    expect(fetch).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('ignores an old in-flight response after restart without creating another polling loop', async () => {
    let resolveOld!: (value: ResearchSnapshot) => void
    const old = new Promise<ResearchSnapshot>(resolve => { resolveOld = resolve })
    const fetch = vi.fn().mockImplementationOnce(() => old).mockResolvedValue(snapshot('ready'))
    let polling!: ReturnType<typeof useResearchPolling>
    const wrapper = mount(defineComponent({ setup() { polling = useResearchPolling(fetch); return () => null } }))
    polling.restart()
    await flushPromises()
    resolveOld(snapshot('failed'))
    await flushPromises()
    expect(polling.job.value?.status).toBe('ready')
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetch).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })
})
