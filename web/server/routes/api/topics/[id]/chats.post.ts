import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useUserSession } from '../../../../utils/session'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const { id } = await getValidatedRouterParams(event, z.object({ id: z.string() }).parse)
  const db = useDrizzle()

  const topic = await db.query.topics.findFirst({
    where: eq(tables.topics.id, id)
  })
  if (!topic) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Topic not found' })
  }

  const [newChat] = await db.insert(tables.chats).values({
    title: '新对话',
    userId: session.data.user?.id || session.id!,
    visibility: 'private',
    topicId: id,
    isBranch: false
  }).returning()

  if (!newChat) {
    throw new HTTPError({ statusCode: 500, statusMessage: 'Failed to create chat' })
  }

  return newChat
})
