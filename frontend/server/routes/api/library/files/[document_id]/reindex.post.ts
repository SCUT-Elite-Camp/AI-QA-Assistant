import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { desc, eq, tables, useDrizzle } from '../../../../../utils/drizzle'
import { requireCsrf } from '../../../../../utils/attachmentAuth'
import { attachmentServiceJson } from '../../../../../utils/attachmentService'
import { requireLibraryDocument } from '../../../../../utils/library'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const documentId = getRouterParam(event, 'document_id') || ''
  const { document } = await requireLibraryDocument(event, documentId)
  const db = useDrizzle()
  const version = (await db.select().from(tables.documentVersions)
    .where(eq(tables.documentVersions.documentId, document.id))
    .orderBy(desc(tables.documentVersions.versionNumber)).limit(1))[0]
  if (!version) throw new HTTPError({ statusCode: 404, statusMessage: 'library_version_not_found' })
  await attachmentServiceJson(`/v1/attachments/${version.storageRef}/retry`, { method: 'POST' })
  await db.update(tables.documentVersions).set({ status: 'REINDEXING', errorCode: '', errorMessage: '', updatedAt: new Date() })
    .where(eq(tables.documentVersions.id, version.id))
  return { document_id: document.id, version_id: version.id, status: 'REINDEXING' }
})
