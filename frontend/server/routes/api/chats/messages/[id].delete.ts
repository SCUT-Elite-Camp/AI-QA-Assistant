import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { defineHandler, HTTPError } from 'nitro'
import { z } from 'zod'
import { useUserSession } from '../../../../utils/session'
import { useDrizzle, tables, eq, and, asc, inArray } from '../../../../utils/drizzle'
import { agentFetch } from '../../../../utils/agent-client'
import { requireOwnedChat } from '../../../../utils/chatAccess'
import { resetShortWindow } from '../../../../utils/agentInternalClient'
import { HistoryMutationError, truncateHistoryAndInvalidateMemory } from '../../../../utils/memoryRepository'
import { cleanupOrphanedAttachments } from '../../../../utils/attachmentCleanup'
import { requireCsrf } from '../../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const session = await useUserSession(event)

  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { chatId } = await readValidatedBody(event, z.object({
    chatId: z.string()
  }).parse)

  const { actor } = await requireOwnedChat(event, chatId)
  const db = useDrizzle()

  // Use the memory repository's optimistic locking to truncate DB messages
  // and invalidate Memory Facts / Snapshots consistently.
  let result: { historyRevision: number }
  try {
    result = await truncateHistoryAndInvalidateMemory(db, {
      actorUserId: actor.userId,
      chatId,
      firstDeletedMessageId: id
    })
  } catch (err) {
    if (err instanceof HistoryMutationError) {
      throw new HTTPError({
        statusCode: err.statusCode,
        statusMessage: err.statusMessage
      })
    }
    throw err
  }

  // Find all message IDs to delete to clean up attachments
  const allMessages = await db.query.messages.findMany({
    where: eq(tables.messages.chatId, chatId),
    orderBy: [asc(tables.messages.sequence), asc(tables.messages.createdAt)]
  })

  const targetMessage = allMessages.find(m => m.id === id)
  if (!targetMessage) {
    return { success: true, historyRevision: result.historyRevision }
  }

  const startIndex = allMessages.findIndex(m => m.id === id)
  const idsToDelete = allMessages.slice(startIndex).map(m => m.id)

  if (idsToDelete.length > 0) {
    const attachmentLinks = await db.query.messageAttachments.findMany({ where: inArray(tables.messageAttachments.messageId, idsToDelete) })
    await db.delete(tables.messages).where(inArray(tables.messages.id, idsToDelete))
    if (attachmentLinks.length) await cleanupOrphanedAttachments(attachmentLinks.map(link => link.attachmentId))
    agentFetch(`/api/chat/memory/${id}`, { method: 'DELETE' }).catch(() => {})
  }
  void resetShortWindow(id).catch(() => {})

  return { success: true, historyRevision: result.historyRevision }
})
