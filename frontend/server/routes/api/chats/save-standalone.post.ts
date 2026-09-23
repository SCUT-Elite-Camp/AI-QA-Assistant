import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables } from '../../../utils/drizzle'
import { appendMessage } from '../../../utils/messageLifecycle'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const db = useDrizzle()

  const { initialQuery, selectedText, contextText, messages } = await readValidatedBody(event, z.object({
    initialQuery: z.string().optional(),
    selectedText: z.string().optional(),
    contextText: z.string().optional(),
    messages: z.array(z.object({
      role: z.string(),
      text: z.string().optional(),
      parts: z.array(z.any()).optional()
    })).optional()
  }).parse)

  const selPrefix = (selectedText || '').trim()
  const qPart = (initialQuery || '').trim()
  const rawTitle = selPrefix ? (qPart ? `${selPrefix}: ${qPart}` : selPrefix) : (qPart || '划选独立会话')
  const title = rawTitle.length > 25 ? rawTitle.slice(0, 25) + '...' : rawTitle

  // Create standalone chat (topicId: null)
  const [newChat] = await db.insert(tables.chats).values({
    title,
    userId: session.data.user?.id || session.id!,
    visibility: 'private',
    topicId: null,
    isBranch: false
  }).returning()

  if (!newChat) {
    throw new HTTPError({ statusCode: 500, statusMessage: '创建独立对话失败' })
  }

  // Insert conversation messages directly (both questions and assistant AI answers)
  if (messages && messages.length > 0) {
    for (const msg of messages) {
      const msgParts = msg.parts && msg.parts.length > 0
        ? msg.parts
        : [{ type: 'text', text: msg.text || '' }]

      await appendMessage(db, {
        chatId: newChat.id,
        role: msg.role === 'user' ? 'user' : 'assistant',
        parts: msgParts
      })
    }
  }

  return {
    chat: newChat
  }
})
