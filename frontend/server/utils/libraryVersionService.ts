import { and, eq, sql, tables, useDrizzle } from './drizzle'
import { attachmentServiceJson } from './attachmentService'

type DocumentRow = typeof tables.libraryDocuments.$inferSelect
type VersionRow = typeof tables.documentVersions.$inferSelect
type DatabaseClient = ReturnType<typeof useDrizzle>
type TransactionClient = Parameters<Parameters<DatabaseClient['transaction']>[0]>[0]
export type LibraryDatabaseExecutor = DatabaseClient | TransactionClient

type InitialDocument = Omit<
  typeof tables.libraryDocuments.$inferInsert,
  'activeVersionId' | 'desiredVersionId' | 'latestVersionNumber'
>
type VersionWithoutNumber = Omit<typeof tables.documentVersions.$inferInsert, 'versionNumber'>
type VersionDocumentMetadata = Pick<
  typeof tables.libraryDocuments.$inferInsert,
  'filename' | 'displayName' | 'mimeType' | 'docType'
>

const documentAllocationTails = new Map<string, Promise<void>>()

async function withDocumentAllocationLock<T>(documentId: string, operation: () => Promise<T>) {
  const previous = documentAllocationTails.get(documentId) ?? Promise.resolve()
  let release!: () => void
  const current = new Promise<void>((resolve) => { release = resolve })
  const tail = previous.then(() => current)
  documentAllocationTails.set(documentId, tail)
  await previous
  try {
    return await operation()
  } finally {
    release()
    if (documentAllocationTails.get(documentId) === tail) {
      documentAllocationTails.delete(documentId)
    }
  }
}

export type HashResolution = 'unchanged' | 'reactivate' | 'retry' | 'pending' | 'create'

export function resolveUploadedHash(
  activeHash: string | undefined,
  uploadedHash: string,
  historicalStatus: VersionRow['status'] | undefined,
): HashResolution {
  if (activeHash === uploadedHash) return 'unchanged'
  if (historicalStatus === 'READY') return 'reactivate'
  if (historicalStatus === 'FAILED') return 'retry'
  if (historicalStatus) return 'pending'
  return 'create'
}

export function desiredActivationMode(
  desiredVersionId: string | null,
  candidate: Pick<VersionRow, 'id' | 'status' | 'versionNumber'>,
  active: Pick<VersionRow, 'versionNumber'> | undefined,
) {
  if (desiredVersionId !== candidate.id || candidate.status !== 'READY') {
    return { allowed: false, explicit: false }
  }
  return {
    allowed: true,
    explicit: Boolean(active && candidate.versionNumber < active.versionNumber),
  }
}

export async function findVersionByHash(
  documentId: string,
  hash: string,
  db: LibraryDatabaseExecutor = useDrizzle(),
) {
  return db.query.documentVersions.findFirst({
    where: and(
      eq(tables.documentVersions.documentId, documentId),
      eq(tables.documentVersions.contentHash, hash),
    )
  })
}

export async function getActiveVersion(
  document: DocumentRow,
  db: LibraryDatabaseExecutor = useDrizzle(),
) {
  if (!document.activeVersionId) return undefined
  return db.query.documentVersions.findFirst({
    where: and(
      eq(tables.documentVersions.id, document.activeVersionId),
      eq(tables.documentVersions.documentId, document.id),
    )
  })
}

export async function insertInitialLibraryDocument(
  tx: LibraryDatabaseExecutor,
  document: InitialDocument,
) {
  await tx.insert(tables.libraryDocuments).values({
    ...document,
    activeVersionId: null,
    desiredVersionId: null,
    latestVersionNumber: 0,
  })
}

export async function insertInitialLibraryVersion(
  tx: LibraryDatabaseExecutor,
  version: VersionWithoutNumber,
) {
  await tx.insert(tables.documentVersions).values({ ...version, versionNumber: 1 })
}

export async function updateInitialLibraryPointers(
  tx: LibraryDatabaseExecutor,
  documentId: string,
  versionId: string,
) {
  const updated = await tx.update(tables.libraryDocuments).set({
    latestVersionNumber: 1,
    desiredVersionId: versionId,
    updatedAt: new Date(),
  }).where(and(
    eq(tables.libraryDocuments.id, documentId),
    eq(tables.libraryDocuments.latestVersionNumber, 0),
    sql`${tables.libraryDocuments.deletedAt} IS NULL`,
  )).returning({ id: tables.libraryDocuments.id })
  if (updated.length !== 1) throw new Error('library_initial_version_pointer_conflict')
}

export async function createDocumentWithInitialVersion(
  document: InitialDocument,
  version: VersionWithoutNumber,
  db: DatabaseClient = useDrizzle(),
) {
  if (version.documentId !== document.id) {
    throw new Error('library_initial_version_document_mismatch')
  }
  await db.transaction(async (tx) => {
    await insertInitialLibraryDocument(tx, document)
    await insertInitialLibraryVersion(tx, version)
    await updateInitialLibraryPointers(tx, document.id, version.id)
  }, { behavior: 'immediate' })
  return 1
}

export async function createLibraryVersion(
  documentId: string,
  version: VersionWithoutNumber,
  documentMetadata?: VersionDocumentMetadata,
  db: DatabaseClient = useDrizzle(),
) {
  return withDocumentAllocationLock(documentId, async () => {
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        return await db.transaction(async (tx) => {
          const document = await tx.query.libraryDocuments.findFirst({
            where: eq(tables.libraryDocuments.id, documentId)
          })
          if (!document || document.deletedAt) throw new Error('library_document_not_found')
          const versionNumber = document.latestVersionNumber + 1
          const updated = await tx.update(tables.libraryDocuments).set({
            ...documentMetadata,
            latestVersionNumber: versionNumber,
            desiredVersionId: version.id,
            updatedAt: new Date(),
          }).where(and(
            eq(tables.libraryDocuments.id, documentId),
            eq(tables.libraryDocuments.latestVersionNumber, document.latestVersionNumber),
            sql`${tables.libraryDocuments.deletedAt} IS NULL`,
          )).returning({ id: tables.libraryDocuments.id })
          if (updated.length !== 1) throw new Error('library_version_allocation_conflict')
          await tx.insert(tables.documentVersions).values({ ...version, versionNumber })
          return versionNumber
        }, { behavior: 'immediate' })
      } catch (error) {
        const message = String(error)
        if (
          message.includes('library_version_allocation_conflict')
          || message.includes('SQLITE_BUSY')
          || message.includes('database is locked')
        ) continue
        throw error
      }
    }
    throw new Error('library_version_allocation_exhausted')
  })
}

export async function setDesiredVersion(documentId: string, versionId: string) {
  await useDrizzle().update(tables.libraryDocuments).set({
    desiredVersionId: versionId,
    updatedAt: new Date(),
  }).where(and(
    eq(tables.libraryDocuments.id, documentId),
    sql`${tables.libraryDocuments.deletedAt} IS NULL`,
  ))
}

export async function activateDesiredVersion(document: DocumentRow, version: VersionRow) {
  const db = useDrizzle()
  const fresh = await db.query.libraryDocuments.findFirst({
    where: and(
      eq(tables.libraryDocuments.id, document.id),
      sql`${tables.libraryDocuments.deletedAt} IS NULL`,
    )
  })
  if (!fresh) return false
  const previousActiveId = fresh.activeVersionId
  const previousActive = previousActiveId
    ? await db.query.documentVersions.findFirst({ where: eq(tables.documentVersions.id, previousActiveId) })
    : undefined
  const activation = desiredActivationMode(fresh.desiredVersionId, version, previousActive)
  if (!activation.allowed) return false
  const updated = await db.update(tables.libraryDocuments).set({
    activeVersionId: version.id,
    updatedAt: new Date(),
  }).where(and(
    eq(tables.libraryDocuments.id, document.id),
    eq(tables.libraryDocuments.desiredVersionId, version.id),
    sql`${tables.libraryDocuments.deletedAt} IS NULL`,
  )).returning({ id: tables.libraryDocuments.id })
  if (updated.length !== 1) return false
  try {
    const remote = await attachmentServiceJson<any>(`/v1/attachments/${version.storageRef}/library/activate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version_number: version.versionNumber, explicit: activation.explicit }),
    })
    if (remote.activated === false && remote.active_id !== version.storageRef) {
      throw new Error('library_remote_activation_rejected')
    }
  } catch (error) {
    await db.update(tables.libraryDocuments).set({ activeVersionId: previousActiveId })
      .where(and(
        eq(tables.libraryDocuments.id, document.id),
        eq(tables.libraryDocuments.activeVersionId, version.id),
        eq(tables.libraryDocuments.desiredVersionId, version.id),
      ))
    throw error
  }
  return true
}
