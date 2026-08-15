import { defineHandler } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { z } from 'zod'
import { requireOwnedChat } from '../../../utils/chatAccess'
import { resetShortWindow } from '../../../utils/agentInternalClient'


export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { actor } = await requireOwnedChat(event, id)
  const db = useDrizzle()

  const deleted = await db.delete(tables.chats)
    .where(and(eq(tables.chats.id, id as string), eq(tables.chats.userId, actor.userId)))
    .returning()

  // The database mutation is authoritative. A reset failure only affects the
  // legacy short-window compatibility path and must not roll back deletion.
  if (deleted.length > 0) {
    void resetShortWindow(id).catch(() => {})
  }

  return deleted
})

