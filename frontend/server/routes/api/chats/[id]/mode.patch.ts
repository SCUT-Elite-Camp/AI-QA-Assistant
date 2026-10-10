import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'
import { getOptionalChatActor, isChatOwnedByActor } from '../../../../utils/chatAccess'
import { requireCsrf, requireTopicRole } from '../../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const { id } = await getValidatedRouterParams(event, z.object({ id: z.string() }).parse)
  const { weightMode } = await readValidatedBody(event, z.object({
    weightMode: z.enum(['auto', 'fast', 'thinking']),
  }).parse)
  const actor = await getOptionalChatActor(event)
  if (!actor) throw new HTTPError({ statusCode: 401, statusMessage: 'Authentication required' })

  const db = useDrizzle()
  const chat = await db.query.chats.findFirst({ where: eq(tables.chats.id, id) })
  if (!chat) throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })

  const ownsChat = isChatOwnedByActor(chat.userId, actor)
  if (!ownsChat && chat.topicId) {
    await requireTopicRole(event, chat.topicId, 'editor')
  } else if (!ownsChat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }

  const [updated] = await db.update(tables.chats)
    .set({ weightMode })
    .where(eq(tables.chats.id, id))
    .returning({ weightMode: tables.chats.weightMode })

  return updated
})
