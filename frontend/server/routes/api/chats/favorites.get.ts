import { defineHandler } from 'nitro'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { requireTopicRole } from '../../../utils/attachmentAuth'
import { requireEnabledActor } from '../../../utils/sourceAccess'

export default defineHandler(async (event) => {
  const userId = await requireEnabledActor(event)
  const db = useDrizzle()
  const chats = await db.select().from(tables.chats).where(eq(tables.chats.userId, userId))
  const favorites = []
  for (const chat of chats) {
    try { if (chat.topicId) await requireTopicRole(event, chat.topicId, 'viewer') }
    catch (error: any) {
      if ([403, 404, 409].includes(error?.status ?? error?.statusCode)) continue
      throw error
    }
    const messages = await db.query.messages.findMany({ where: (messages, { and, eq }) => and(eq(messages.chatId, chat.id), eq(messages.isFavorite, true)) })
    if (messages.length) {
      favorites.push({ id: chat.id, title: chat.title, lastFavoritedAt: chat.updatedAt, favoriteMessages: messages })
    }
  }
  return favorites
})
