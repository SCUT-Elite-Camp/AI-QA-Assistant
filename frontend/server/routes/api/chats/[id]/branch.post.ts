import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { useDrizzle, tables, eq, and } from '../../../../utils/drizzle'
import { requireCsrf, requirePrincipal, requireTopicRole } from '../../../../utils/attachmentAuth'
import { requireOwnedChat } from '../../../../utils/chatAccess'
import { appendMessage } from '../../../../utils/messageLifecycle'
import { assertMessageSources, authoredProvenance } from '../../../../utils/sourceAccess'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requirePrincipal(event)
  const { id } = await getValidatedRouterParams(event, z.object({ id: z.string() }).parse)
  const { chat: parentChat } = await requireOwnedChat(event, id, 'editor')
  const body = await readValidatedBody(event, z.object({
    initialQuery: z.string().optional(), parentMessageId: z.string().optional(),
    selectedText: z.string().optional(), contextText: z.string().optional(),
    messages: z.array(z.object({ id: z.string().min(1), role: z.string().optional(), text: z.string().optional(), parts: z.array(z.any()).optional() })).max(24).optional(),
  }).parse)
  const db = useDrizzle()
  if (parentChat.topicId) await requireTopicRole(event, parentChat.topicId, 'viewer')
  const copies = []
  for (const request of body.messages || []) {
    const message = await db.query.messages.findFirst({ where: and(eq(tables.messages.id, request.id), eq(tables.messages.chatId, parentChat.id)) })
    if (!message) throw new HTTPError({ statusCode: 404, statusMessage: 'source_message_not_found' })
    await assertMessageSources(userId, message)
    copies.push(message)
  }
  if (body.parentMessageId) {
    const selected = await db.query.messages.findFirst({ where: and(eq(tables.messages.id, body.parentMessageId), eq(tables.messages.chatId, parentChat.id)) })
    if (!selected) throw new HTTPError({ statusCode: 404, statusMessage: 'source_message_not_found' })
    await assertMessageSources(userId, selected)
  }
  let topicId = parentChat.topicId
  if (!topicId) {
    const [topic] = await db.insert(tables.topics).values({ title: '话题项目', mainChatId: parentChat.id, soulContent: '', evidenceProvenance: authoredProvenance(), weightMode: 'thinking' }).returning()
    if (!topic) throw new HTTPError({ statusCode: 500, statusMessage: 'topic_create_failed' })
    topicId = topic.id
    await db.insert(tables.topicMembers).values({ topicId, userId, role: 'owner' }).onConflictDoNothing()
    await db.update(tables.chats).set({ topicId }).where(eq(tables.chats.id, parentChat.id))
  }
  const [branchChat] = await db.insert(tables.chats).values({
    title: '分支对话', userId, visibility: 'private', topicId, isBranch: true, parentChatId: parentChat.id,
    evidenceProvenance: authoredProvenance(),
    parentMessageId: body.parentMessageId || null, historyRevision: 1, nextMessageSequence: 1,
  }).returning()
  if (!branchChat) throw new HTTPError({ statusCode: 500, statusMessage: 'chat_create_failed' })
  for (const message of copies) await appendMessage(db, { chatId: branchChat.id, role: message.role, parts: message.parts })
  if (!copies.length && body.initialQuery) await appendMessage(db, { chatId: branchChat.id, role: 'user', parts: [
    { type: 'text', text: body.initialQuery },
    { type: 'data-evidence-provenance', data: { schema_version: 'evidence.provenance.v1', complete: true, dependencies: [] } },
  ] })
  return { branchChat, topicId }
})
