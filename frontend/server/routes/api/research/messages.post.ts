import { and, eq } from 'drizzle-orm'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { requireCsrf, requirePrincipal } from '../../../utils/attachmentAuth'
import { appendMessage } from '../../../utils/messageLifecycle'
import { tables, useDrizzle } from '../../../utils/drizzle'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const body = await readValidatedBody(event, z.object({
    chatId: z.string().regex(/^research-[a-zA-Z0-9]+$/),
    messageId: z.string().min(1).max(160),
    text: z.string().min(1),
    createdAt: z.string().datetime().optional(),
  }).parse)
  const db = useDrizzle()
  const userId = await requirePrincipal(event)
  const chat = await db.query.chats.findFirst({
    where: and(eq(tables.chats.id, body.chatId), eq(tables.chats.userId, userId)),
  })
  if (!chat) throw new HTTPError({ statusCode: 404, statusMessage: 'Research conversation not found' })

  const existing = await db.query.messages.findFirst({
    where: and(eq(tables.messages.id, body.messageId), eq(tables.messages.chatId, body.chatId)),
  })
  if (existing) return existing

  return appendMessage(db, {
    id: body.messageId,
    chatId: body.chatId,
    role: 'assistant',
    parts: [{ type: 'text', text: body.text }],
  })
})
