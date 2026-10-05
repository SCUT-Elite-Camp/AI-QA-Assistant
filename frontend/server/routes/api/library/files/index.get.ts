import { defineHandler } from 'nitro'
import { desc, eq, tables, useDrizzle } from '../../../../utils/drizzle'
import { requirePrincipal } from '../../../../utils/attachmentAuth'
import { getOrCreateDefaultLibrary, personalLibraryDocumentPredicate } from '../../../../utils/library'

export default defineHandler(async (event) => {
  const userId = await requirePrincipal(event)
  const db = useDrizzle()
  const library = await getOrCreateDefaultLibrary(userId, db)
  const documents = await db.select().from(tables.libraryDocuments)
    .where(personalLibraryDocumentPredicate(userId, library.id))
    .orderBy(desc(tables.libraryDocuments.updatedAt))
  const files = await Promise.all(documents.map(async document => {
    const versions = await db.select().from(tables.documentVersions)
      .where(eq(tables.documentVersions.documentId, document.id))
      .orderBy(desc(tables.documentVersions.createdAt))
    const current = versions.find(item => item.id === document.activeVersionId) || versions[0]
    return { ...document, status: current?.status || 'UPLOADED', error_code: current?.errorCode || '', latest_version_id: versions[0]?.id, versions }
  }))
  return { files }
})
