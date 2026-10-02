import { defineHandler } from 'nitro'
import { useDrizzle, tables, eq } from '../../utils/drizzle'
import { requirePrincipal } from '../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  const db = useDrizzle()
  const userId = await requirePrincipal(event)
  const userChats = await db.select().from(tables.chats).where(eq(tables.chats.userId, userId))

  return userChats.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
})
