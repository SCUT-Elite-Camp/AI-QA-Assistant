import { createHash } from 'node:crypto'
import { HTTPError } from 'nitro'
import type { HTTPEvent } from 'nitro/h3'
import { and, eq, sql, tables, useDrizzle } from './drizzle'
import { requirePrincipal } from './attachmentAuth'
import { attachmentServiceJson } from './attachmentService'

export type LibraryStatus = 'UPLOADED' | 'PARSING' | 'CHUNKING' | 'EMBEDDING' | 'INDEXING' | 'READY' | 'FAILED' | 'REINDEXING'

export function mapLibraryStatus(remote: string): LibraryStatus {
  if (remote === 'ready' || remote === 'needs_review') return 'READY'
  if (remote === 'failed' || remote === 'quarantined') return 'FAILED'
  if (remote === 'parsing') return 'PARSING'
  if (remote === 'chunking') return 'CHUNKING'
  if (remote === 'embedding') return 'EMBEDDING'
  if (remote === 'indexing') return 'INDEXING'
  return 'UPLOADED'
}

export async function getOrCreateDefaultLibrary(userId: string) {
  const db = useDrizzle()
  let library = await db.query.knowledgeBases.findFirst({
    where: and(
      eq(tables.knowledgeBases.ownerUserId, userId),
      eq(tables.knowledgeBases.scopeType, 'personal'),
      sql`${tables.knowledgeBases.deletedAt} IS NULL`
    )
  })
  if (library) return library
  // Deterministic default identity makes concurrent first access idempotent
  // without preventing additional personal knowledge bases in the future.
  const id = `kb_${createHash('sha256').update(userId).digest('hex').slice(0, 32)}`
  await db.insert(tables.knowledgeBases).values({
    id, name: 'My Library', scopeType: 'personal', ownerUserId: userId,
    createdAt: new Date(), updatedAt: new Date()
  }).onConflictDoNothing()
  library = await db.query.knowledgeBases.findFirst({
    where: and(eq(tables.knowledgeBases.ownerUserId, userId), eq(tables.knowledgeBases.scopeType, 'personal'))
  })
  if (!library) throw new HTTPError({ statusCode: 500, statusMessage: 'library_create_failed' })
  return library
}

export async function requireLibraryDocument(event: HTTPEvent, documentId: string) {
  const userId = await requirePrincipal(event)
  const document = await useDrizzle().query.libraryDocuments.findFirst({
    where: and(
      eq(tables.libraryDocuments.id, documentId),
      eq(tables.libraryDocuments.ownerUserId, userId),
      eq(tables.libraryDocuments.sourceScope, 'personal'),
      sql`${tables.libraryDocuments.deletedAt} IS NULL`
    )
  })
  if (!document) throw new HTTPError({ statusCode: 404, statusMessage: 'library_document_not_found' })
  return { userId, document }
}

export async function syncLibraryVersion(version: typeof tables.documentVersions.$inferSelect) {
  const remote = await attachmentServiceJson<any>(`/v1/attachments/${version.storageRef}`)
  const status = mapLibraryStatus(String(remote.status || ''))
  const now = new Date()
  const db = useDrizzle()
  await db.update(tables.documentVersions).set({
    status,
    errorCode: String(remote.error_code || ''),
    errorMessage: String(remote.error_code || ''),
    updatedAt: now,
    indexedAt: status === 'READY' ? now : version.indexedAt
  }).where(eq(tables.documentVersions.id, version.id))
  if (status === 'READY') {
    await db.update(tables.libraryDocuments).set({ activeVersionId: version.id, updatedAt: now })
      .where(eq(tables.libraryDocuments.id, version.documentId))
  }
  return { ...version, status, errorCode: String(remote.error_code || ''), updatedAt: now, remote }
}
