import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq, and } from '../../../../../utils/drizzle'
import { syncTopicToDisk } from '../../../../../utils/topicStorage'
import { requireCsrf, requireTopicRole } from '../../../../../utils/attachmentAuth'


export default defineHandler(async (event) => {
  const { id, docId } = await getValidatedRouterParams(event, z.object({
    id: z.string(),
    docId: z.string()
  }).parse)
  requireCsrf(event)
  await requireTopicRole(event, id, 'editor')

  const db = useDrizzle()

  await db.update(tables.topicDocuments)
    .set({ isRemoved: true })
    .where(and(
      eq(tables.topicDocuments.topicId, id),
      eq(tables.topicDocuments.docId, docId)
    ))

  const topic = await db.query.topics.findFirst({ where: eq(tables.topics.id, id) })
  const docs = await db.query.topicDocuments.findMany({ where: eq(tables.topicDocuments.topicId, id) })
  if (topic) {
    syncTopicToDisk(topic.id, topic, topic.soulContent, docs)
  }

  return { status: 'ok', topicId: id, docId }
})

