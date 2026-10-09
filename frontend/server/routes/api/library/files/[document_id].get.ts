import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { desc, eq, tables, useDrizzle } from '../../../../utils/drizzle'
import { requireLibraryDocument } from '../../../../utils/library'

export default defineHandler(async (event) => {
  const documentId = getRouterParam(event, 'document_id') || ''
  const { document } = await requireLibraryDocument(event, documentId)
  const versions = await useDrizzle().select().from(tables.documentVersions)
    .where(eq(tables.documentVersions.documentId, document.id))
    .orderBy(desc(tables.documentVersions.createdAt))
  return { ...document, versions }
})
