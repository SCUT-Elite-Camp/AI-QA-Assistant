import { definePlugin } from 'nitro'
import { drainLibraryCleanupJobs } from '../utils/libraryCleanup'
import { logger } from '../utils/logger'
import { syncPendingLibraryVersions } from '../utils/library'

export default definePlugin((nitroApp) => {
  const configured = Number(process.env.LIBRARY_CLEANUP_POLL_MS || 5000)
  const intervalMs = Number.isFinite(configured) ? Math.max(1000, configured) : 5000
  let running = false
  const run = async () => {
    if (running) return
    running = true
    try {
      await drainLibraryCleanupJobs()
      if (process.env.ATTACHMENTS_ENABLED === 'true') await syncPendingLibraryVersions()
    } catch (error) {
      logger.error({ event: 'LIBRARY_CLEANUP_WORKER_ERROR', err: error }, 'library cleanup worker failed')
    } finally {
      running = false
    }
  }
  void run()
  const timer = setInterval(() => { void run() }, intervalMs)
  timer.unref?.()
  nitroApp.hooks.hook('close', () => clearInterval(timer))
})
