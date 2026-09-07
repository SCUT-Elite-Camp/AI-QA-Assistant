import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { ResearchJob } from '../types/research'
import { isResearchTerminal } from '../utils/research'

export function useResearchPolling(fetchJob: () => Promise<ResearchJob>, intervalMs = 1600) {
  const job = ref<ResearchJob | null>(null)
  const loading = ref(true)
  const error = ref<unknown>(null)
  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false

  function stop() {
    stopped = true
    if (timer) clearTimeout(timer)
    timer = null
  }

  async function refresh() {
    if (stopped) return
    try {
      job.value = await fetchJob()
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

  return { job, loading, error, refresh, restart, stop }
}

