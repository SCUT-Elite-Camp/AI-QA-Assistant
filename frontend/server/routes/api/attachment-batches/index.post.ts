import { randomUUID } from 'node:crypto'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { requireCsrf, requirePrincipal, requireTopicRole } from '../../../utils/attachmentAuth'
import { eq, tables, useDrizzle } from '../../../utils/drizzle'
import { isAnonymousAttachmentPrincipal, validBatchReferences } from '../../../../shared/utils/attachmentScope'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requirePrincipal(event)
  const body = await readValidatedBody(event, z.object({
    scope: z.enum(['draft', 'chat', 'topic']),
    chat_id: z.string().nullable().optional(),
    topic_id: z.string().nullable().optional()
  }).parse)
  if (!validBatchReferences(body.scope, body.chat_id, body.topic_id)) {
    throw new HTTPError({ statusCode: 422, statusMessage: 'invalid_batch_scope_references' })
  }
  let authoritativeChatTopicId: string | null = null
  if (body.scope === 'topic') {
    if (isAnonymousAttachmentPrincipal(userId)) {
      throw new HTTPError({ statusCode: 403, statusMessage: 'anonymous_topic_attachment_forbidden' })
    }
    await requireTopicRole(event, body.topic_id!, 'editor')
  }
  if (body.scope === 'chat' && body.chat_id) {
    const chat = await useDrizzle().query.chats.findFirst({ where: eq(tables.chats.id, body.chat_id) })
    if (!chat) throw new HTTPError({ statusCode: 404, statusMessage: 'chat_not_found' })
    if (body.topic_id && body.topic_id !== chat.topicId) {
      throw new HTTPError({ statusCode: 409, statusMessage: 'chat_topic_mismatch' })
    }
    authoritativeChatTopicId = chat.topicId
    if (chat.topicId) await requireTopicRole(event, chat.topicId, 'editor')
    else if (chat.userId !== userId) throw new HTTPError({ statusCode: 403, statusMessage: 'chat_forbidden' })
  }
  const expiresAt = body.scope === 'topic' ? null : new Date(Date.now() + 24 * 60 * 60 * 1000)
  const [batch] = await useDrizzle().insert(tables.attachmentBatches).values({
    id: `atb_${randomUUID().replace(/-/g, '')}`,
    ownerId: userId,
    scope: body.scope,
    chatId: body.chat_id || null,
    topicId: body.scope === 'chat' ? authoritativeChatTopicId : (body.topic_id || null),
    expiresAt,
  }).returning()
  return batch
})
