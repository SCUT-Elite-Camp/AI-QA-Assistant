import { defineHandler } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { z } from 'zod'


export default defineHandler(async (event) => {
  const session = await useUserSession(event)

  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const db = useDrizzle()

  // Clear agent memory asynchronously (ignore network errors if Agent is offline)
  fetch(`http://127.0.0.1:8000/api/chat/memory/${id}`, { method: 'DELETE' }).catch(() => {})

  return await db.delete(tables.chats)
    .where(and(eq(tables.chats.id, id as string), eq(tables.chats.userId, session.data.user?.id || session.id!)))
    .returning()
})

