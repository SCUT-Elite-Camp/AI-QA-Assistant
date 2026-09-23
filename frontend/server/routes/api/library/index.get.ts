import { defineHandler } from 'nitro'
import { and, eq, sql, tables, useDrizzle } from '../../../utils/drizzle'
import { requirePrincipal } from '../../../utils/attachmentAuth'
import { getOrCreateDefaultLibrary } from '../../../utils/library'

export default defineHandler(async (event) => {
  const userId = await requirePrincipal(event)
  const library = await getOrCreateDefaultLibrary(userId)
  const documents = await useDrizzle().select({ count: sql<number>`count(*)` })
    .from(tables.libraryDocuments)
    .where(and(eq(tables.libraryDocuments.knowledgeBaseId, library.id), sql`${tables.libraryDocuments.deletedAt} IS NULL`))
  return { ...library, file_count: Number(documents[0]?.count || 0) }
})
