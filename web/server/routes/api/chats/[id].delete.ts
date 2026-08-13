import { defineHandler } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { z } from 'zod'
import { getAgentBaseUrl, requireOwnedChat } from '../../../utils/chatAccess'


export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { actor } = await requireOwnedChat(event, id)
  const db = useDrizzle()

  // Clear agent memory asynchronously (ignore network errors if Agent is offline)
  fetch(`${getAgentBaseUrl()}/api/chat/memory/${id}`, {
    method: 'DELETE'
  }).catch(() => {})

  return await db.delete(tables.chats)
    .where(and(eq(tables.chats.id, id as string), eq(tables.chats.userId, actor.userId)))
    .returning()
})

