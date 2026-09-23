import { defineHandler } from 'nitro'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { loadAllFavoritesFromDisk } from '../../../utils/favoriteStorage'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const db = useDrizzle()
  const userId = session.data.user?.id || session.id!

  // ── Primary source: disk (data-persistence/data/favorites/) ─────────────
  const diskRecords = loadAllFavoritesFromDisk()

  if (diskRecords.length > 0) {
    // Map disk records back to chat-list format (same shape as /api/chats)
    return diskRecords.map(r => ({
      id: r.chatId,
      title: r.chatTitle,
      lastFavoritedAt: r.lastUpdatedAt,
      favoriteMessages: r.messages
    }))
  }

  // ── Fallback: query DB for messages with isFavorite=true ─────────────────
  let userChats = await db.select().from(tables.chats).where(eq(tables.chats.userId, userId))
  if (!userChats || userChats.length === 0) {
    userChats = await db.select().from(tables.chats)
  }

  const favMessages = await db.select().from(tables.messages).where(eq(tables.messages.isFavorite, true))
  const favChatIds = new Set(favMessages.map(m => m.chatId))

  const favoriteChats = userChats.filter(c => favChatIds.has(c.id))

  return favoriteChats
    .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    .map(c => ({
      id: c.id,
      title: c.title || 'Untitled',
      lastFavoritedAt: c.updatedAt,
      favoriteMessages: []
    }))
})
