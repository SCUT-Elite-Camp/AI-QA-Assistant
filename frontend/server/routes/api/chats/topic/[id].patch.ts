import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { useUserSession } from '../../../../utils/session'
import { useDrizzle, tables, eq, and } from '../../../../utils/drizzle'
import { z } from 'zod'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)

  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { topicId } = await readValidatedBody(event, z.object({
    topicId: z.string().nullable()
  }).parse)

  const db = useDrizzle()
  const userId = session.data.user?.id || session.id!

  const chat = await db.query.chats.findFirst({
    where: eq(tables.chats.id, id)
  })

  if (!chat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }

  // Verify topic exists if topicId is provided
  if (topicId) {
    const topic = await db.query.topics.findFirst({
      where: eq(tables.topics.id, topicId)
    })
    if (!topic) {
      throw new HTTPError({ statusCode: 404, statusMessage: 'Topic space not found' })
    }
  }

  const [updated] = await db.update(tables.chats)
    .set({ topicId })
    .where(eq(tables.chats.id, id))
    .returning()

  if (!updated) {
    throw new HTTPError({ statusCode: 500, statusMessage: 'Failed to update chat topic' })
  }

  return updated
})
