import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { readableTopic, readableTopicDocuments } from '../../../utils/topicEvidence'
import { readableChatMetadata } from '../../../utils/sourceAccess'
import { requireTopicRole } from '../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)
  const { userId } = await requireTopicRole(event, id, 'viewer')

  const db = useDrizzle()

  const topic = await db.query.topics.findFirst({
    where: eq(tables.topics.id, id),
    with: {
      documents: true
    }
  })

  if (!topic) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Topic space not found' })
  }

  // Read latest soul.md and topic_info from data-persistence layer folder on disk
  const visible = await readableTopic(userId, topic)

  // Return Knowledge documents (user-uploaded reference files ONLY) for topic settings
  const userUploadedDocs = (topic.documents || []).filter((d: any) => d.isUserUploaded && !d.isRemoved)

  return {
    ...visible,
    ...(topic.chats ? { chats: await Promise.all(topic.chats.map(chat => readableChatMetadata(userId, chat))) } : {}),
    documents: await readableTopicDocuments(userId, userUploadedDocs)
  }
})
