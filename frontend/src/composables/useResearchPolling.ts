import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { ResearchEvent, ResearchJob, ResearchProgress, ResearchSnapshot } from '../types/research'
import { isResearchTerminal } from '../utils/research'

export function useResearchPolling(
  fetchSnapshot: (afterEventId: number) => Promise<ResearchSnapshot>,
  intervalMs = 5000,
) {
  const job = ref<ResearchJob | null>(null)
  const progress = ref<ResearchProgress | null>(null)
  const events = ref<ResearchEvent[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)
  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false
  let generation = 0
  let eventCursor = 0

  function stop() {
    stopped = true
    generation += 1
    if (timer) clearTimeout(timer)
    timer = null
  }

  async function refresh() {
    if (stopped) return
    const activeGeneration = generation
    try {
      const { job: nextJob, progress: nextProgress, events: nextEvents } = await fetchSnapshot(eventCursor)
      if (stopped || activeGeneration !== generation) return
      job.value = nextJob
      progress.value = nextProgress
      if (nextEvents.events.length) {
        const known = new Set(events.value.map(item => item.event_id))
        events.value = [...events.value, ...nextEvents.events.filter(item => !known.has(item.event_id))].slice(-50)
      }
      eventCursor = nextEvents.next_after_event_id
      error.value = null
      if (isResearchTerminal(job.value)) {
        loading.value = false
        return stop()
      }
    } catch (reason) {
      if (!stopped && activeGeneration === generation) error.value = reason
    } finally {
      if (activeGeneration === generation) loading.value = false
    }
    if (!stopped && activeGeneration === generation) timer = setTimeout(refresh, document.hidden ? intervalMs * 3 : intervalMs)
  }

  function restart() {
    stop()
    stopped = false
    void refresh()
  }

  onMounted(refresh)
  onBeforeUnmount(stop)

  return { job, progress, events, loading, error, refresh, restart, stop }
}
