import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useDrizzle } from '../../../../utils/drizzle'
import { getAgentBaseUrl, requireOwnedChat } from '../../../../utils/chatAccess'
import { MessageLifecycleError, truncateHistory } from '../../../../utils/messageLifecycle'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  await requireOwnedChat(event, id)

  const { messageId, type } = await readValidatedBody(event, z.object({
    messageId: z.string(),
    type: z.enum(['edit', 'regenerate'])
  }).parse)

  const db = useDrizzle()

  let result
  try {
    result = await truncateHistory(db, {
      chatId: id,
      messageId,
      type
    })
  } catch (error) {
    if (error instanceof MessageLifecycleError) {
      throw new HTTPError({ statusCode: error.statusCode, statusMessage: error.message })
    }
    throw error
  }

  if (result.deletedMessageIds.length > 0) {
    // Clear Agent in-memory history so regenerate/edit rebuilds clean context
    fetch(`${getAgentBaseUrl()}/api/chat/memory/${id}`, {
      method: 'DELETE'
    }).catch(() => {})
  }

  return { success: true, historyRevision: result.historyRevision }
})
