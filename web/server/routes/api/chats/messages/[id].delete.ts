import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
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

  // The history transaction has committed; reset failure must not undo it.
  // This is only the legacy short-window compatibility path.
  void resetShortWindow(id).catch(() => {})

  return { success: true, historyRevision: result.historyRevision }
})
