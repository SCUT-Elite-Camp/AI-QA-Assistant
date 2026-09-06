import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { ResearchEvent, ResearchEventsResponse, ResearchJob, ResearchProgress } from '../types/research'
import { isResearchTerminal } from '../utils/research'

export function useResearchPolling(
  fetchJob: () => Promise<ResearchJob>,
  fetchProgress: () => Promise<ResearchProgress>,
  fetchEvents: (afterEventId: number) => Promise<ResearchEventsResponse>,
  intervalMs = 1600,
) {
  const job = ref<ResearchJob | null>(null)
  const progress = ref<ResearchProgress | null>(null)
  const events = ref<ResearchEvent[]>([])
  const loading = ref(true)
  const error = ref<unknown>(null)
  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false
  let eventCursor = 0

  function stop() {
    stopped = true
    if (timer) clearTimeout(timer)
    timer = null
  }

  async function refresh() {
    if (stopped) return
    try {
      const [nextJob, nextProgress, nextEvents] = await Promise.all([
        fetchJob(),
        fetchProgress(),
        fetchEvents(eventCursor),
      ])
      job.value = nextJob
      progress.value = nextProgress
      if (nextEvents.events.length) {
        const known = new Set(events.value.map(item => item.event_id))
        events.value = [...events.value, ...nextEvents.events.filter(item => !known.has(item.event_id))].slice(-50)
      }
      eventCursor = nextEvents.next_after_event_id
      error.value = null
      if (isResearchTerminal(job.value)) return stop()
    } catch (reason) {
      error.value = reason
    } finally {
      loading.value = false
    }
    if (!stopped) timer = setTimeout(refresh, document.hidden ? intervalMs * 3 : intervalMs)
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

