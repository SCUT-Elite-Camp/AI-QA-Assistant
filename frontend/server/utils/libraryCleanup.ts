import { randomUUID } from 'node:crypto'
import { and, asc, eq, sql, tables, useDrizzle } from './drizzle'
import { attachmentServiceFetch } from './attachmentService'
import { personalLibraryDocumentPredicate } from './library'
import { logger } from './logger'
import {
  recordLibraryCleanupAttempt,
  setLibraryCleanupGauges,
} from './metrics'

type DatabaseClient = ReturnType<typeof useDrizzle>
type CleanupJob = typeof tables.libraryCleanupJobs.$inferSelect

export interface CleanupProcessorDependencies {
  deleteRemote?: (remoteObjectId: string) => Promise<Response>
  now?: () => Date
  random?: () => number
}

export function cleanupBackoffMs(attemptCount: number, random = Math.random) {
  const base = Math.min(6 * 60 * 60 * 1000, 1000 * (2 ** Math.max(0, attemptCount - 1)))
  return Math.round(base * (0.75 + random() * 0.5))
}

export async function softDeleteDocumentWithCleanup(
  documentId: string,
  ownerUserId: string,
  knowledgeBaseId: string,
  db: DatabaseClient = useDrizzle(),
) {
  return db.transaction(async (tx) => {
    const document = await tx.query.libraryDocuments.findFirst({
      where: personalLibraryDocumentPredicate(ownerUserId, knowledgeBaseId, documentId),
    })
    if (!document) throw new Error('library_document_not_found')
    const versions = await tx.select().from(tables.documentVersions)
      .where(eq(tables.documentVersions.documentId, document.id))
    if (versions.length === 0) throw new Error('library_document_has_no_versions')
    const now = new Date()
    const deleted = await tx.update(tables.libraryDocuments).set({
      deletedAt: now,
      activeVersionId: null,
      desiredVersionId: null,
      updatedAt: now,
    }).where(personalLibraryDocumentPredicate(ownerUserId, knowledgeBaseId, documentId))
      .returning({ id: tables.libraryDocuments.id })
    if (deleted.length !== 1) throw new Error('library_document_delete_conflict')

    await tx.insert(tables.libraryCleanupJobs).values(versions.map(version => ({
      id: `cleanup_${randomUUID().replace(/-/g, '')}`,
      action: 'delete_version' as const,
      documentId: document.id,
      versionId: version.id,
      remoteObjectId: version.storageRef,
      ownerUserId,
      knowledgeBaseId,
      idempotencyKey: `delete-version:${version.id}`,
      status: 'pending' as const,
      attemptCount: 0,
      maxAttempts: 10,
      nextAttemptAt: now,
      createdAt: now,
      updatedAt: now,
    }))).onConflictDoNothing({ target: tables.libraryCleanupJobs.idempotencyKey })

    return tx.select().from(tables.libraryCleanupJobs)
      .where(eq(tables.libraryCleanupJobs.documentId, document.id))
  }, { behavior: 'immediate' })
}

async function claimCleanupJob(
  db: DatabaseClient,
  jobId: string | undefined,
  now: Date,
) {
  const nowEpoch = Math.floor(now.getTime() / 1000)
  return db.transaction(async (tx) => {
    const eligible = sql`(
      (${tables.libraryCleanupJobs.status} IN ('pending','retry')
        AND ${tables.libraryCleanupJobs.nextAttemptAt} <= ${nowEpoch})
      OR (${tables.libraryCleanupJobs.status} = 'processing'
        AND ${tables.libraryCleanupJobs.leaseExpiresAt} <= ${nowEpoch})
    )`
    const candidate = await tx.query.libraryCleanupJobs.findFirst({
      where: and(
        jobId ? eq(tables.libraryCleanupJobs.id, jobId) : undefined,
        eligible,
        sql`${tables.libraryCleanupJobs.attemptCount} < ${tables.libraryCleanupJobs.maxAttempts}`,
      ),
      orderBy: [asc(tables.libraryCleanupJobs.nextAttemptAt), asc(tables.libraryCleanupJobs.createdAt)],
    })
    if (!candidate) return undefined
    const claimToken = randomUUID()
    const claimed = await tx.update(tables.libraryCleanupJobs).set({
      status: 'processing',
      claimToken,
      claimedAt: now,
      leaseExpiresAt: new Date(now.getTime() + 60_000),
      attemptCount: sql`${tables.libraryCleanupJobs.attemptCount} + 1`,
      updatedAt: now,
    }).where(and(eq(tables.libraryCleanupJobs.id, candidate.id), eligible))
      .returning()
    return claimed[0]
  }, { behavior: 'immediate' })
}

function safeError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  return message.replace(/[\r\n]/g, ' ').slice(0, 300)
}

async function updateClaimedJob(
  db: DatabaseClient,
  job: CleanupJob,
  values: Partial<typeof tables.libraryCleanupJobs.$inferInsert>,
) {
  await db.update(tables.libraryCleanupJobs).set(values).where(and(
    eq(tables.libraryCleanupJobs.id, job.id),
    eq(tables.libraryCleanupJobs.claimToken, job.claimToken || ''),
    eq(tables.libraryCleanupJobs.status, 'processing'),
  ))
}

export async function processLibraryCleanupJob(
  jobId?: string,
  db: DatabaseClient = useDrizzle(),
  dependencies: CleanupProcessorDependencies = {},
) {
  const now = dependencies.now?.() ?? new Date()
  const job = await claimCleanupJob(db, jobId, now)
  if (!job) return undefined
  const deleteRemote = dependencies.deleteRemote
    ?? ((remoteObjectId: string) => attachmentServiceFetch(
      `/v1/attachments/${encodeURIComponent(remoteObjectId)}`,
      { method: 'DELETE' },
    ))
  let response: Response | undefined
  let errorCode = ''
  let errorMessage = ''
  try {
    response = await deleteRemote(job.remoteObjectId)
    if (response.ok || response.status === 404) {
      await updateClaimedJob(db, job, {
        status: 'completed',
        completedAt: now,
        claimToken: null,
        claimedAt: null,
        leaseExpiresAt: null,
        lastErrorCode: '',
        lastErrorMessage: '',
        updatedAt: now,
      })
      recordLibraryCleanupAttempt(true)
      logger.info({
        event: 'LIBRARY_CLEANUP_COMPLETE',
        jobId: job.id,
        documentId: job.documentId,
        versionId: job.versionId,
        attemptCount: job.attemptCount,
      }, 'library cleanup completed')
      return { ...job, status: 'completed' as const }
    }
    errorCode = `http_${response.status}`
    errorMessage = `attachment_delete_http_${response.status}`
  } catch (error) {
    errorCode = 'network_error'
    errorMessage = safeError(error)
  }

  const permanentClientError = Boolean(
    response && response.status >= 400 && response.status < 500 && response.status !== 429,
  )
  const exhausted = job.attemptCount >= job.maxAttempts
  const status = permanentClientError || exhausted ? 'dead' : 'retry'
  await updateClaimedJob(db, job, {
    status,
    nextAttemptAt: status === 'retry'
      ? new Date(now.getTime() + cleanupBackoffMs(job.attemptCount, dependencies.random))
      : now,
    claimToken: null,
    claimedAt: null,
    leaseExpiresAt: null,
    lastErrorCode: errorCode,
    lastErrorMessage: errorMessage,
    updatedAt: now,
  })
  recordLibraryCleanupAttempt(false)
  logger[status === 'dead' ? 'error' : 'warn']({
    event: status === 'dead' ? 'LIBRARY_CLEANUP_DEAD' : 'LIBRARY_CLEANUP_RETRY',
    jobId: job.id,
    documentId: job.documentId,
    versionId: job.versionId,
    attemptCount: job.attemptCount,
    errorCode,
  }, `library cleanup ${status}`)
  return { ...job, status, lastErrorCode: errorCode }
}

export async function refreshLibraryCleanupMetrics(db: DatabaseClient = useDrizzle()) {
  const rows = await db.select({
    status: tables.libraryCleanupJobs.status,
    count: sql<number>`count(*)`,
    oldest: sql<number | null>`min(${tables.libraryCleanupJobs.createdAt})`,
  }).from(tables.libraryCleanupJobs)
    .where(sql`${tables.libraryCleanupJobs.status} IN ('pending','retry','dead')`)
    .groupBy(tables.libraryCleanupJobs.status)
  const counts = new Map(rows.map(row => [row.status, Number(row.count)]))
  const oldest = rows
    .filter(row => row.status === 'pending' || row.status === 'retry')
    .map(row => Number(row.oldest || 0))
    .filter(Boolean)
  setLibraryCleanupGauges({
    pending: counts.get('pending') || 0,
    retry: counts.get('retry') || 0,
    dead: counts.get('dead') || 0,
    oldestPendingAgeSeconds: oldest.length
      ? Math.max(0, Math.floor((Date.now() - Math.min(...oldest) * 1000) / 1000))
      : 0,
  })
}

export async function drainLibraryCleanupJobs(
  limit = 10,
  db: DatabaseClient = useDrizzle(),
) {
  let processed = 0
  while (processed < limit) {
    const result = await processLibraryCleanupJob(undefined, db)
    if (!result) break
    processed++
  }
  await refreshLibraryCleanupMetrics(db)
  return processed
}

export async function getCleanupJobsForDocument(
  documentId: string,
  db: DatabaseClient = useDrizzle(),
) {
  return db.select().from(tables.libraryCleanupJobs)
    .where(eq(tables.libraryCleanupJobs.documentId, documentId))
    .orderBy(asc(tables.libraryCleanupJobs.createdAt))
}

export type { CleanupJob }
