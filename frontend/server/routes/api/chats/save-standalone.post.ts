import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { useDrizzle, tables, eq, and } from '../../../utils/drizzle'
import { appendMessage } from '../../../utils/messageLifecycle'
import { requireCsrf } from '../../../utils/attachmentAuth'
import { requireOwnedChat } from '../../../utils/chatAccess'
import { authoredProvenance, assertMessageSources, requireEnabledActor } from '../../../utils/sourceAccess'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requireEnabledActor(event)
  const body = await readValidatedBody(event, z.object({
    initialQuery: z.string().optional(), selectedText: z.string().optional(), contextText: z.string().optional(),
    sourceChatId: z.string().optional(),
    messages: z.array(z.object({ id: z.string().min(1), role: z.string().optional(), text: z.string().optional(), parts: z.array(z.any()).optional() })).max(24).optional(),
  }).parse)
  const db = useDrizzle()
  const copies = []
  if (body.messages?.length) {
    if (!body.sourceChatId) throw new HTTPError({ statusCode: 409, statusMessage: 'source_message_required' })
    await requireOwnedChat(event, body.sourceChatId)
    for (const request of body.messages) {
      const message = await db.query.messages.findFirst({ where: and(eq(tables.messages.id, request.id), eq(tables.messages.chatId, body.sourceChatId)) })
      if (!message) throw new HTTPError({ statusCode: 404, statusMessage: 'source_message_not_found' })
      await assertMessageSources(userId, message)
      copies.push(message)
    }
  }
  const [chat] = await db.insert(tables.chats).values({ title: '独立对话', userId, evidenceProvenance: authoredProvenance(), visibility: 'private', topicId: null, isBranch: false,
    parentChatId: body.sourceChatId || null }).returning()
  if (!chat) throw new HTTPError({ statusCode: 500, statusMessage: 'chat_create_failed' })
  for (const message of copies) await appendMessage(db, { chatId: chat.id, role: message.role, parts: message.parts })
  if (!copies.length && body.initialQuery) await appendMessage(db, { chatId: chat.id, role: 'user', parts: [
    { type: 'text', text: body.initialQuery },
    { type: 'data-evidence-provenance', data: { schema_version: 'evidence.provenance.v1', complete: true, dependencies: [] } },
  ] })
  return { chat }
})
