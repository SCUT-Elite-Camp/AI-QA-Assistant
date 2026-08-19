import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { useDrizzle, tables, eq, and } from '../../../../utils/drizzle'
import { requestTopicSummarizerFromPersistence } from '../../../../utils/soul'
import { copyChatCitationsToTopic } from '../../../../utils/topicStorage'
import { requireCsrf, requirePrincipal, requireTopicRole } from '../../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requirePrincipal(event)
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { initialQuery, parentMessageId, selectedText, contextText, messages } = await readValidatedBody(event, z.object({
    initialQuery: z.string().optional(),
    parentMessageId: z.string().optional(),
    selectedText: z.string().optional(),
    contextText: z.string().optional(),
    messages: z.array(z.object({
      id: z.string().optional(),
      role: z.string(),
      text: z.string().optional(),
      parts: z.array(z.any()).optional()
    })).optional()
  }).parse)

  const db = useDrizzle()

  const parentChat = await db.query.chats.findFirst({
    where: eq(tables.chats.id, id),
    with: { messages: true }
  })

  if (!parentChat) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Parent chat not found' })
  }
  if (parentChat.topicId) await requireTopicRole(event, parentChat.topicId, 'viewer')
  else if (parentChat.userId !== userId) throw new HTTPError({ statusCode: 403, statusMessage: 'chat_forbidden' })

  const selPrefix = (selectedText || '').trim()
  const qPart = (initialQuery || '').trim()
  const rawTitle = selPrefix ? (qPart ? `${selPrefix}: ${qPart}` : selPrefix) : (qPart || parentChat.title || '分支探讨')
  const branchTitle = rawTitle.length > 25 ? rawTitle.slice(0, 25) + '...' : rawTitle

  // Ensure parent chat has a topic, or create topic space
  let topicId = parentChat.topicId
  if (!topicId) {
    const [newTopic] = await db.insert(tables.topics).values({
      title: parentChat.title || '话题项目',
      mainChatId: parentChat.id,
      soulContent: `# 话题认知: ${parentChat.title || '分支探讨'}`,
      weightMode: 'auto',
      consecutiveNoNewDocsCount: 0
    }).returning()

    topicId = newTopic.id
    await db.insert(tables.topicMembers).values({ topicId, userId, role: 'owner' }).onConflictDoNothing()
    await db.update(tables.chats).set({ topicId }).where(eq(tables.chats.id, parentChat.id))

    void (async () => {
      try {
        const summary = await requestTopicSummarizerFromPersistence(
          topicId!, parentChat.title || rawTitle, parentChat.title || undefined,
        )
        if (summary) {
          await db.update(tables.topics).set({
            title: summary.title,
            soulContent: summary.soulContent,
            description: summary.description,
            tags: summary.tags,
          }).where(eq(tables.topics.id, topicId!))
        }
      } catch (err) {
        console.error('[AsyncSoul] Error updating topic soul in background:', err)
      }
    })()
  }

  // Create formal branch chat
  const [branchChat] = await db.insert(tables.chats).values({
    title: branchTitle,
    userId,
    visibility: 'private',
    topicId,
    isBranch: true,
    parentChatId: parentChat.id,
    parentMessageId: parentMessageId || null
  }).returning()

  // Insert all passed conversation messages (both questions and assistant AI answers)
  if (messages && messages.length > 0) {
    for (const msg of messages) {
      const msgParts = msg.parts && msg.parts.length > 0
        ? msg.parts.filter(part => part?.type !== 'data-attachment')
        : [{ type: 'text', text: msg.text || '' }]

      const original = msg.id
        ? parentChat.messages.find(message => message.id === msg.id)
        : undefined

      const [newMessage] = await db.insert(tables.messages).values({
        chatId: branchChat.id,
        role: msg.role === 'user' ? 'user' : 'assistant',
        parts: original?.parts || msgParts
      }).returning()
      if (original) {
          const links = await db.query.messageAttachments.findMany({
            where: and(eq(tables.messageAttachments.messageId, original.id))
          })
          if (links.length) {
            await db.insert(tables.messageAttachments).values(links.map(link => ({
              messageId: newMessage.id,
              attachmentId: link.attachmentId,
              evidenceVersion: link.evidenceVersion,
            }))).onConflictDoNothing()
          }
      }
    }
  } else if (initialQuery) {
    await db.insert(tables.messages).values({
      chatId: branchChat.id,
      role: 'user',
      parts: [{ type: 'text', text: initialQuery }]
    })
  }

  return {
    branchChat,
    topicId
  }
})
