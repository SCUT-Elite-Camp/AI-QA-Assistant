import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle } from '../../../utils/drizzle'
import { z } from 'zod'
import { assertResearchChatAccess, getOptionalChatActor, isChatOwnedByActor } from '../../../utils/chatAccess'
import { requirePrincipal, requireTopicRole } from '../../../utils/attachmentAuth'
import { filterReadableMessages, readableChatMetadata, requireEnabledActor } from '../../../utils/sourceAccess'

export default defineHandler(async (event) => {
  const userId = await requireEnabledActor(event)
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const chat = await useDrizzle().query.chats.findFirst({
    where: (chat, { eq }) => eq(chat.id, id as string),
    with: {
      messages: {
        orderBy: (message, { asc }) => asc(message.sequence)
      }
    }
  })

  if (!chat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }

  const actor = await getOptionalChatActor(event)
  await assertResearchChatAccess(event, id)
  const isOwner = actor ? isChatOwnedByActor(chat.userId, actor) : false
  let topicRole: 'owner' | 'editor' | 'viewer' | null = null
  if (chat.topicId) {
    topicRole = (await requireTopicRole(event, chat.topicId, 'viewer')).role
  } else if (chat.visibility === 'private' && !isOwner) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Chat not found' })
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { userId: _, ...rest } = chat
  return { ...await readableChatMetadata(userId, rest), messages: await filterReadableMessages(userId, chat.messages), isOwner, topicRole }
})
