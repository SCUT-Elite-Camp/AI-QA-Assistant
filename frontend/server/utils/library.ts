import { createHash } from 'node:crypto'
import { HTTPError } from 'nitro'
import type { HTTPEvent } from 'nitro/h3'
import { and, eq, sql, tables, useDrizzle } from './drizzle'
import { requirePrincipal } from './attachmentAuth'
import { attachmentServiceJson } from './attachmentService'
import { activateDesiredVersion } from './libraryVersionService'
import type { LibraryDatabaseExecutor } from './libraryVersionService'

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

export async function getOrCreateDefaultLibrary(
  userId: string,
  db: LibraryDatabaseExecutor = useDrizzle(),
) {
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
    where: and(
      eq(tables.knowledgeBases.ownerUserId, userId),
      eq(tables.knowledgeBases.scopeType, 'personal'),
      sql`${tables.knowledgeBases.deletedAt} IS NULL`,
    )
  })
  if (!library) throw new HTTPError({ statusCode: 500, statusMessage: 'library_create_failed' })
  return library
}

export function personalLibraryDocumentPredicate(
  userId: string,
  knowledgeBaseId: string,
  documentId?: string,
) {
  return and(
    documentId ? eq(tables.libraryDocuments.id, documentId) : undefined,
    eq(tables.libraryDocuments.ownerUserId, userId),
    eq(tables.libraryDocuments.knowledgeBaseId, knowledgeBaseId),
    eq(tables.libraryDocuments.sourceScope, 'personal'),
    sql`${tables.libraryDocuments.deletedAt} IS NULL`,
  )
}

export async function getPersonalLibraryDocument(
  userId: string,
  knowledgeBaseId: string,
  documentId: string,
  db: LibraryDatabaseExecutor = useDrizzle(),
) {
  return db.query.libraryDocuments.findFirst({
    where: personalLibraryDocumentPredicate(userId, knowledgeBaseId, documentId),
  })
}

export async function requireLibraryDocument(event: HTTPEvent, documentId: string) {
  const userId = await requirePrincipal(event)
  const library = await getOrCreateDefaultLibrary(userId)
  const document = await getPersonalLibraryDocument(userId, library.id, documentId)
  if (!document) throw new HTTPError({ statusCode: 404, statusMessage: 'library_document_not_found' })
  return { userId, library, document }
}

export async function syncLibraryVersion(
  version: typeof tables.documentVersions.$inferSelect,
  authorizedDocument?: typeof tables.libraryDocuments.$inferSelect,
) {
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
    const document = authorizedDocument || await db.query.libraryDocuments.findFirst({
      where: and(
        eq(tables.libraryDocuments.id, version.documentId),
        eq(tables.libraryDocuments.sourceScope, 'personal'),
        sql`${tables.libraryDocuments.deletedAt} IS NULL`,
      )
    })
    if (document) {
      await activateDesiredVersion(document, { ...version, status, indexedAt: now, updatedAt: now })
    }
  }
  return { ...version, status, errorCode: String(remote.error_code || ''), updatedAt: now, remote }
}
