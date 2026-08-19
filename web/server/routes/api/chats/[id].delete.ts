import { defineHandler } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq, and, inArray } from '../../../utils/drizzle'
import { z } from 'zod'
import { cleanupOrphanedAttachments } from '../../../utils/attachmentCleanup'
import { requireCsrf, requirePrincipal } from '../../../utils/attachmentAuth'


export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requirePrincipal(event)

  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const db = useDrizzle()
  const chatMessages = await db.query.messages.findMany({ where: eq(tables.messages.chatId, id as string) })
  const links = chatMessages.length
    ? await db.query.messageAttachments.findMany({ where: inArray(tables.messageAttachments.messageId, chatMessages.map(message => message.id)) })
    : []

  // Clear agent memory asynchronously (ignore network errors if Agent is offline)
  fetch(`http://127.0.0.1:8000/api/chat/memory/${id}`, { method: 'DELETE' }).catch(() => {})

  const deleted = await db.delete(tables.chats)
    .where(and(eq(tables.chats.id, id as string), eq(tables.chats.userId, userId)))
    .returning()
  if (deleted.length) await cleanupOrphanedAttachments(links.map(link => link.attachmentId))
  return deleted
})

