import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { loadTopicFromDisk, getTopicDocumentsFromDisk } from '../../../utils/topicStorage'
import { requireTopicRole } from '../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)
  await requireTopicRole(event, id, 'viewer')

  const db = useDrizzle()

  const topic = await db.query.topics.findFirst({
    where: eq(tables.topics.id, id),
    with: {
      chats: true,
      documents: true
    }
  })

  if (!topic) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Topic space not found' })
  }

  // Read latest soul.md and topic_info from data-persistence layer folder on disk
  const diskData = loadTopicFromDisk(id)
  const diskDocs = getTopicDocumentsFromDisk(id)

  return {
    ...topic,
    soulContent: diskData?.soulContent || topic.soulContent,
    weightMode: diskData?.topicInfo?.weightMode || topic.weightMode,
    tags: diskData?.topicInfo?.tags || topic.tags || [],
    documents: diskDocs.length ? diskDocs : topic.documents
  }
})
