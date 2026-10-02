import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { useDrizzle } from '../../../../utils/drizzle'
import { requireCsrf } from '../../../../utils/attachmentAuth'
import { requireLibraryDocument } from '../../../../utils/library'
import {
  getCleanupJobsForDocument,
  processLibraryCleanupJob,
  refreshLibraryCleanupMetrics,
  softDeleteDocumentWithCleanup,
} from '../../../../utils/libraryCleanup'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const documentId = getRouterParam(event, 'document_id') || ''
  const { userId, library, document } = await requireLibraryDocument(event, documentId)
  const db = useDrizzle()
  // Logical deletion is the privacy boundary. Remote blobs and indexes are
  // projections. The durable jobs are committed in the same transaction so
  // a process crash cannot lose physical cleanup work.
  const jobs = await softDeleteDocumentWithCleanup(
    document.id,
    userId,
    library.id,
    db,
  )
  await Promise.allSettled(jobs.map(job => processLibraryCleanupJob(job.id, db)))
  const refreshed = await getCleanupJobsForDocument(document.id, db)
  await refreshLibraryCleanupMetrics(db)
  const cleanupStatus = refreshed.every(job => job.status === 'completed')
    ? 'completed'
    : refreshed.some(job => job.status === 'dead') ? 'dead' : 'pending'
  return {
    deleted: true,
    cleanup_pending: cleanupStatus !== 'completed',
    cleanupStatus,
    cleanupOperationId: jobs[0]?.id || null,
    cleanupOperationIds: jobs.map(job => job.id),
  }
})
