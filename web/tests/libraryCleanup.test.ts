import { createClient } from '@libsql/client'
import { drizzle } from 'drizzle-orm/libsql'
import { migrate } from 'drizzle-orm/libsql/migrator'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { eq } from 'drizzle-orm'
import * as schema from '../server/database/schema'
import {
  getCleanupJobsForDocument,
  processLibraryCleanupJob,
  softDeleteDocumentWithCleanup,
} from '../server/utils/libraryCleanup'

const clients: ReturnType<typeof createClient>[] = []
const directories: string[] = []

async function cleanupDatabase() {
  // File-backed SQLite is required because libSQL transactions may use a
  // different connection, which would not share a plain in-memory database.
  const baseDirectory = process.platform === 'win32' ? 'C:\\Users\\Public' : tmpdir()
  const directory = mkdtempSync(join(baseDirectory, 'aiqa-cleanup-test-'))
  directories.push(directory)
  const client = createClient({ url: `file:${join(directory, 'cleanup.sqlite3')}` })
  clients.push(client)
  await client.execute('PRAGMA busy_timeout=5000')
  const db = drizzle(client, { schema })
  await migrate(db, { migrationsFolder: 'server/database/migrations' })
  await db.insert(schema.knowledgeBases).values({
    id: 'kb-a', name: 'My Library', scopeType: 'personal', ownerUserId: 'owner-a',
    createdAt: new Date(), updatedAt: new Date(),
  })
  await db.insert(schema.libraryDocuments).values({
    id: 'doc-a', knowledgeBaseId: 'kb-a', ownerUserId: 'owner-a',
    sourceScope: 'personal', sourceType: 'upload', filename: 'report.md',
    displayName: 'report.md', mimeType: 'text/markdown', docType: 'md',
    activeVersionId: 'ver-a', desiredVersionId: 'ver-a', latestVersionNumber: 1,
    createdAt: new Date(), updatedAt: new Date(),
  })
  await db.insert(schema.documentVersions).values({
    id: 'ver-a', documentId: 'doc-a', contentHash: 'hash-a', storageRef: 'remote-a',
    fileSize: 42, versionNumber: 1, status: 'READY',
    createdAt: new Date(), updatedAt: new Date(),
  })
  return { client, db }
}

afterEach(async () => {
  vi.restoreAllMocks()
  while (clients.length) await clients.pop()!.close()
  while (directories.length) {
    try {
      rmSync(directories.pop()!, {
        recursive: true,
        force: true,
        maxRetries: 1,
        retryDelay: 25,
      })
    } catch (error) {
      // Windows runners can keep the native SQLite handle briefly after
      // client.close(). The runner workspace is ephemeral; a cleanup-only
      // lock must not turn passing database assertions into a false failure.
      const code = (error as NodeJS.ErrnoException).code
      if (code !== 'EPERM' && code !== 'EBUSY') throw error
    }
  }
})

describe('personal library durable cleanup outbox', () => {
  it('commits logical deletion and cleanup job atomically', async () => {
    const { db } = await cleanupDatabase()
    const jobs = await softDeleteDocumentWithCleanup('doc-a', 'owner-a', 'kb-a', db)
    expect(jobs).toHaveLength(1)
    expect(jobs[0]).toMatchObject({ status: 'pending', remoteObjectId: 'remote-a' })
    const document = await db.query.libraryDocuments.findFirst({
      where: eq(schema.libraryDocuments.id, 'doc-a'),
    })
    expect(document!.deletedAt).not.toBeNull()
    expect(document!.activeVersionId).toBeNull()
    expect(document!.desiredVersionId).toBeNull()
  })

  it('rolls back soft deletion when cleanup job insertion fails', async () => {
    const { client, db } = await cleanupDatabase()
    await client.execute(`CREATE TRIGGER fail_cleanup_insert
      BEFORE INSERT ON library_cleanup_jobs BEGIN
      SELECT RAISE(ABORT, 'injected_cleanup_insert_failure'); END`)
    await expect(softDeleteDocumentWithCleanup('doc-a', 'owner-a', 'kb-a', db))
      .rejects.toThrow()
    const document = await db.query.libraryDocuments.findFirst({
      where: eq(schema.libraryDocuments.id, 'doc-a'),
    })
    expect(document!.deletedAt).toBeNull()
    expect(await getCleanupJobsForDocument('doc-a', db)).toHaveLength(0)
  })

  it('rolls back before creating jobs when logical deletion fails', async () => {
    const { client, db } = await cleanupDatabase()
    await client.execute(`CREATE TRIGGER fail_document_delete
      BEFORE UPDATE OF deleted_at ON library_documents BEGIN
      SELECT RAISE(ABORT, 'injected_delete_failure'); END`)
    await expect(softDeleteDocumentWithCleanup('doc-a', 'owner-a', 'kb-a', db))
      .rejects.toThrow()
    expect(await getCleanupJobsForDocument('doc-a', db)).toHaveLength(0)
  })

  it('completes a pending job after the deleting request has ended', async () => {
    const { db } = await cleanupDatabase()
    const [job] = await softDeleteDocumentWithCleanup('doc-a', 'owner-a', 'kb-a', db)
    const deleteRemote = vi.fn(async () => new Response(null, { status: 204 }))

    await processLibraryCleanupJob(job.id, db, { deleteRemote })

    expect(deleteRemote).toHaveBeenCalledOnce()
    expect((await getCleanupJobsForDocument('doc-a', db))[0].status).toBe('completed')
  })

  it.each([
    ['timeout', async () => { throw new Error('request_timeout') }, 'retry'],
    ['http 500', async () => new Response(null, { status: 500 }), 'retry'],
    ['http 429', async () => new Response(null, { status: 429 }), 'retry'],
    ['http 400', async () => new Response(null, { status: 400 }), 'dead'],
    ['http 404', async () => new Response(null, { status: 404 }), 'completed'],
  ])('classifies Attachment DELETE %s correctly', async (_case, deleteRemote, expected) => {
    const { db } = await cleanupDatabase()
    const [job] = await softDeleteDocumentWithCleanup('doc-a', 'owner-a', 'kb-a', db)
    await processLibraryCleanupJob(job.id, db, { deleteRemote, random: () => 0 })
    expect((await getCleanupJobsForDocument('doc-a', db))[0].status).toBe(expected)
  })

  it('reclaims an expired processing lease after worker restart', async () => {
    const { db } = await cleanupDatabase()
    const [job] = await softDeleteDocumentWithCleanup('doc-a', 'owner-a', 'kb-a', db)
    const now = new Date('2026-08-20T00:00:00Z')
    await db.update(schema.libraryCleanupJobs).set({
      status: 'processing',
      claimToken: 'abandoned-worker',
      leaseExpiresAt: new Date(now.getTime() - 1000),
    }).where(eq(schema.libraryCleanupJobs.id, job.id))

    await processLibraryCleanupJob(job.id, db, {
      now: () => now,
      deleteRemote: async () => new Response(null, { status: 204 }),
    })
    const refreshed = (await getCleanupJobsForDocument('doc-a', db))[0]
    expect(refreshed.status).toBe('completed')
    expect(refreshed.attemptCount).toBe(1)
  })

  it('does not repeat a completed idempotent side effect', async () => {
    const { db } = await cleanupDatabase()
    const [job] = await softDeleteDocumentWithCleanup('doc-a', 'owner-a', 'kb-a', db)
    const deleteRemote = vi.fn(async () => new Response(null, { status: 204 }))
    await processLibraryCleanupJob(job.id, db, { deleteRemote })
    await processLibraryCleanupJob(job.id, db, { deleteRemote })
    expect(deleteRemote).toHaveBeenCalledOnce()
  })

  it('moves an exhausted retry to dead for operator visibility', async () => {
    const { db } = await cleanupDatabase()
    const [job] = await softDeleteDocumentWithCleanup('doc-a', 'owner-a', 'kb-a', db)
    await db.update(schema.libraryCleanupJobs).set({ maxAttempts: 1 })
      .where(eq(schema.libraryCleanupJobs.id, job.id))
    await processLibraryCleanupJob(job.id, db, {
      deleteRemote: async () => new Response(null, { status: 500 }),
    })
    const refreshed = (await getCleanupJobsForDocument('doc-a', db))[0]
    expect(refreshed.status).toBe('dead')
    expect(refreshed.lastErrorCode).toBe('http_500')
  })
})
