import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'

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

  const allChats = await db.query.chats.findMany({
    where: eq(tables.chats.topicId, id),
    with: {
      messages: true
    }
  })

  // Format main chat first, then branch chats sorted by creation time
  const mainChat = allChats.find(c => c.id === topic.mainChatId || !c.isBranch) || allChats[0]
  const branchChats = allChats.filter(c => c.id !== mainChat?.id).sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime())

  return {
    mainChat,
    branchChats,
    totalCount: allChats.length
  }
})
