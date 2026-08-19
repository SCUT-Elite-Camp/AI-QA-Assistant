import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { eq, tables, useDrizzle } from '../../../../utils/drizzle'
import { requireCsrf } from '../../../../utils/attachmentAuth'
import { attachmentServiceFetch } from '../../../../utils/attachmentService'
import { requireLibraryDocument } from '../../../../utils/library'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const documentId = getRouterParam(event, 'document_id') || ''
  const { document } = await requireLibraryDocument(event, documentId)
  const db = useDrizzle()
  const versions = await db.select().from(tables.documentVersions)
    .where(eq(tables.documentVersions.documentId, document.id))
  await Promise.all(versions.map(async version => {
    const response = await attachmentServiceFetch(`/v1/attachments/${version.storageRef}`, { method: 'DELETE' })
    if (!response.ok && response.status !== 404) throw new Error('library_index_delete_failed')
  }))
  await db.update(tables.libraryDocuments).set({ deletedAt: new Date(), activeVersionId: null, updatedAt: new Date() })
    .where(eq(tables.libraryDocuments.id, document.id))
  return { deleted: true }
})
