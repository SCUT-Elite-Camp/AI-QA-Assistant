import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { desc, eq, tables, useDrizzle } from '../../../../../utils/drizzle'
import { requireLibraryDocument, syncLibraryVersion } from '../../../../../utils/library'

export default defineHandler(async (event) => {
  const documentId = getRouterParam(event, 'document_id') || ''
  const { document } = await requireLibraryDocument(event, documentId)
  const version = (await useDrizzle().select().from(tables.documentVersions)
    .where(eq(tables.documentVersions.documentId, document.id))
    .orderBy(desc(tables.documentVersions.versionNumber)).limit(1))[0]
  if (!version) throw new HTTPError({ statusCode: 404, statusMessage: 'library_version_not_found' })
  const synced = await syncLibraryVersion(version, document)
  const refreshed = await useDrizzle().query.libraryDocuments.findFirst({ where: eq(tables.libraryDocuments.id, document.id) })
  return { document_id: document.id, active_version_id: refreshed?.activeVersionId || null, version_id: version.id, version_number: version.versionNumber, status: synced.status, error_code: synced.errorCode }
})
