import { defineHandler } from 'nitro'
import { useUserSession } from '../../utils/session'
import { useDrizzle, tables, eq } from '../../utils/drizzle'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const db = useDrizzle()
  const userId = session.data.user?.id || session.id!

  let userChats = await db.select().from(tables.chats).where(eq(tables.chats.userId, userId))

  // In local unauthenticated dev mode, if session ID refreshed, adopt existing local chats to current session
  if ((!userChats || userChats.length === 0) && !session.data.user) {
    const allChats = await db.select().from(tables.chats)
    for (const chat of allChats) {
      await db.update(tables.chats).set({ userId }).where(eq(tables.chats.id, chat.id))
    }
    userChats = allChats
  }

  return userChats.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
})
