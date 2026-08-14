import { z } from 'zod'
import { defineHandler } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'
import { generateTopicTitle, generateInitialSoul } from '../../../../utils/soul'
import { requireOwnedChat } from '../../../../utils/chatAccess'
import { appendMessage } from '../../../../utils/messageLifecycle'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { actor, chat: parentChat } = await requireOwnedChat(event, id)

  const { initialQuery, parentMessageId, selectedText, contextText, messages } = await readValidatedBody(event, z.object({
    initialQuery: z.string().optional(),
    parentMessageId: z.string().optional(),
    selectedText: z.string().optional(),
    contextText: z.string().optional(),
    messages: z.array(z.object({
      role: z.string(),
      text: z.string().optional(),
      parts: z.array(z.any()).optional()
    })).optional()
  }).parse)

  const db = useDrizzle()

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
    await db.update(tables.chats).set({ topicId }).where(eq(tables.chats.id, parentChat.id))

    void (async () => {
      try {
        const title = await generateTopicTitle(parentChat.title || rawTitle)
        const soulContent = await generateInitialSoul(title, parentChat.title || rawTitle, [])
        await db.update(tables.topics).set({ title, soulContent }).where(eq(tables.topics.id, topicId!))
      } catch (err) {
        console.error('[AsyncSoul] Error updating topic soul in background:', err)
      }
    })()
  }

  // Create formal branch chat
  const [branchChat] = await db.insert(tables.chats).values({
    title: branchTitle,
    userId: actor.userId,
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
        ? msg.parts
        : [{ type: 'text', text: msg.text || '' }]

      await appendMessage(db, {
        chatId: branchChat.id,
        role: msg.role === 'user' ? 'user' : 'assistant',
        parts: msgParts
      })
    }
  } else if (initialQuery) {
    await appendMessage(db, {
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
