import { z } from 'zod'
import { defineHandler } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq, and } from '../../../../utils/drizzle'
import { getTopicDocumentsFromDisk } from '../../../../utils/topicStorage'
import { requireTopicRole } from '../../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)
  await requireTopicRole(event, id, 'viewer')

  const db = useDrizzle()

  // 1. Fetch DB documents
  const dbDocs = await db.query.topicDocuments.findMany({
    where: and(
      eq(tables.topicDocuments.topicId, id),
      eq(tables.topicDocuments.isRemoved, false)
    )
  })

  // 2. Fetch Disk documents directly from data-persistence/data/topics/<id>/
  const diskDocs = getTopicDocumentsFromDisk(id)

  // 3. Merge DB + Disk documents by docId
  const docMap = new Map<string, any>()
  for (const doc of diskDocs) {
    docMap.set(doc.docId, doc)
  }
  for (const doc of dbDocs) {
    if (!doc.isRemoved) {
      docMap.set(doc.docId, {
        ...docMap.get(doc.docId),
        ...doc
      })
    }
  }

  const allDocs = Array.from(docMap.values())

  // Sort by recallCount desc, then lastRecalledAt desc
  allDocs.sort((a, b) => {
    if ((b.recallCount || 0) !== (a.recallCount || 0)) return (b.recallCount || 0) - (a.recallCount || 0)
    const timeA = a.lastRecalledAt ? new Date(a.lastRecalledAt).getTime() : 0
    const timeB = b.lastRecalledAt ? new Date(b.lastRecalledAt).getTime() : 0
    return timeB - timeA
  })

  return allDocs
})
