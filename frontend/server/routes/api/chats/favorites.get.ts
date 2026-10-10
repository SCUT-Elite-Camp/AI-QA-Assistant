import { defineHandler } from 'nitro'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { requireOwnedChat } from '../../../utils/chatAccess'
import { assertMessageSources, requireEnabledActor } from '../../../utils/sourceAccess'

export default defineHandler(async (event) => {
  const userId = await requireEnabledActor(event)
  const db = useDrizzle()
  const chats = await db.select().from(tables.chats).where(eq(tables.chats.userId, userId))
  const favorites = []
  for (const chat of chats) {
    try { await requireOwnedChat(event, chat.id) }
    catch (error: any) {
      if ([403, 404, 409].includes(error?.status ?? error?.statusCode)) continue
      throw error
    }
    const messages = await db.query.messages.findMany({ where: (messages, { and, eq }) => and(eq(messages.chatId, chat.id), eq(messages.isFavorite, true)) })
    const visible = []
    for (const message of messages) {
      try { await assertMessageSources(userId, message); visible.push(message) } catch { /* legacy/revoked bodies stay inaccessible */ }
    }
    if (visible.length) favorites.push({ id: chat.id, title: '收藏对话', lastFavoritedAt: chat.updatedAt, favoriteMessages: visible })
  }
  return favorites
})
