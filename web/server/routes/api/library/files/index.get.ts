import { defineHandler } from 'nitro'
import { and, desc, eq, sql, tables, useDrizzle } from '../../../../utils/drizzle'
import { requirePrincipal } from '../../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  const userId = await requirePrincipal(event)
  const db = useDrizzle()
  const documents = await db.select().from(tables.libraryDocuments)
    .where(and(eq(tables.libraryDocuments.ownerUserId, userId), sql`${tables.libraryDocuments.deletedAt} IS NULL`))
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
