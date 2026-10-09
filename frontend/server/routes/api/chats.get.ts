import { defineHandler } from 'nitro'
import { useDrizzle, tables, eq } from '../../utils/drizzle'
import { requirePrincipal } from '../../utils/attachmentAuth'
import { readableChatMetadata } from '../../utils/sourceAccess'

export default defineHandler(async (event) => {
  const db = useDrizzle()
  const userId = await requirePrincipal(event)
  const userChats = await db.select().from(tables.chats).where(eq(tables.chats.userId, userId))

  const readable = await Promise.all(userChats.map(chat => readableChatMetadata(userId, chat)))
  return readable.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
})
