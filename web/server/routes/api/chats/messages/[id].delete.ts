import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useUserSession } from '../../../../utils/session'
import { useDrizzle, tables, eq, and, asc, inArray } from '../../../../utils/drizzle'
import { agentFetch } from '../../../../utils/agent-client'
import { useDrizzle } from '../../../../utils/drizzle'
import { requireOwnedChat } from '../../../../utils/chatAccess'
import { resetShortWindow } from '../../../../utils/agentInternalClient'
import { HistoryMutationError, truncateHistoryAndInvalidateMemory } from '../../../../utils/memoryRepository'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { actor } = await requireOwnedChat(event, id)

  const { messageId, type } = await readValidatedBody(event, z.object({
    messageId: z.string(),
    type: z.enum(['edit', 'regenerate'])
  }).parse)

  const db = useDrizzle()

  let result
  try {
    result = await truncateHistoryAndInvalidateMemory(db, {
      actorUserId: actor.userId,
      chatId: id,
      messageId,
      type
    })
  } catch (error) {
    if (error instanceof HistoryMutationError) {
      throw new HTTPError({ statusCode: error.statusCode, statusMessage: error.message })
    }
    throw error
  }

  const targetRole = allMessages[targetIndex]!.role
  if (type === 'edit' && targetRole !== 'user') {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Can only edit user messages' })
  }
  if (type === 'regenerate' && targetRole !== 'assistant') {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Can only regenerate assistant messages' })
  }

  const startIndex = type === 'edit' ? targetIndex + 1 : targetIndex
  const idsToDelete = allMessages.slice(startIndex).map(m => m.id)

  if (idsToDelete.length > 0) {
    await db.delete(tables.messages).where(inArray(tables.messages.id, idsToDelete))
    // Clear Agent in-memory history so regenerate/edit rebuilds clean context
    agentFetch(`/api/chat/memory/${id}`, { method: 'DELETE' }).catch(() => {})
  }
  // The history transaction has committed; reset failure must not undo it.
  // This is only the legacy short-window compatibility path.
  void resetShortWindow(id).catch(() => {})

  return { success: true, historyRevision: result.historyRevision }
})
