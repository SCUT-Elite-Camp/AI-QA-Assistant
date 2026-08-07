import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { deleteTopicFromDisk } from '../../../utils/topicStorage'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const db = useDrizzle()

  const topic = await db.query.topics.findFirst({
    where: eq(tables.topics.id, id)
  })

  if (!topic) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Topic space not found' })
  }

  // 1. Unlink chats
  await db.update(tables.chats).set({ topicId: null }).where(eq(tables.chats.topicId, id))

  // 2. Delete topic documents
  await db.delete(tables.topicDocuments).where(eq(tables.topicDocuments.topicId, id))

  // 3. Delete topic record
  await db.delete(tables.topics).where(eq(tables.topics.id, id))

  // 4. Clean up disk folder data-persistence/data/topics/<id>/
  deleteTopicFromDisk(id)

  return { status: 'ok', id }
})
