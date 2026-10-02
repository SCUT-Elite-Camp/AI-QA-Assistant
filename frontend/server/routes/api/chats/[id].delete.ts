import { defineHandler } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq, and, inArray } from '../../../utils/drizzle'
import { agentFetch } from '../../../utils/agent-client'
import { z } from 'zod'
import { requireOwnedChat } from '../../../utils/chatAccess'
import { resetShortWindow } from '../../../utils/agentInternalClient'
import { cleanupOrphanedAttachments } from '../../../utils/attachmentCleanup'
import { requireCsrf, requirePrincipal } from '../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requirePrincipal(event)
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { actor } = await requireOwnedChat(event, id)
  const db = useDrizzle()
  const chatMessages = await db.query.messages.findMany({ where: eq(tables.messages.chatId, id as string) })
  const links = chatMessages.length
    ? await db.query.messageAttachments.findMany({ where: inArray(tables.messageAttachments.messageId, chatMessages.map(message => message.id)) })
    : []

  const deleted = await db.delete(tables.chats)
    .where(and(eq(tables.chats.id, id as string), eq(tables.chats.userId, actor.userId)))
    .returning()

  if (deleted.length > 0) {
    // Reset only after deletion succeeds; configuration errors are best effort too.
    void Promise.resolve().then(() => agentFetch(`/api/chat/memory/${id}`, { method: 'DELETE' })).catch(() => {})
    if (links.length) await cleanupOrphanedAttachments(links.map(link => link.attachmentId))
    void resetShortWindow(id).catch(() => {})
  }

  return deleted
})
