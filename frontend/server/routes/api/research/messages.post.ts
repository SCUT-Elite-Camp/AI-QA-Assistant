import { and, eq } from 'drizzle-orm'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useUserSession } from '../../../utils/session'
import { tables, useDrizzle } from '../../../utils/drizzle'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const body = await readValidatedBody(event, z.object({
    chatId: z.string().regex(/^research-[a-zA-Z0-9]+$/),
    messageId: z.string().min(1).max(160),
    text: z.string().min(1),
    createdAt: z.string().datetime().optional(),
  }).parse)
  const db = useDrizzle()
  const userId = session.data.user?.id || session.id!
  const chat = await db.query.chats.findFirst({
    where: and(eq(tables.chats.id, body.chatId), eq(tables.chats.userId, userId)),
  })
  if (!chat) throw new HTTPError({ statusCode: 404, statusMessage: 'Research conversation not found' })

  const existing = await db.query.messages.findFirst({
    where: and(eq(tables.messages.id, body.messageId), eq(tables.messages.chatId, body.chatId)),
  })
  if (existing) return existing

  const [message] = await db.insert(tables.messages).values({
    id: body.messageId,
    chatId: body.chatId,
    role: 'assistant',
    parts: [{ type: 'text', text: body.text }],
    ...(body.createdAt ? { createdAt: new Date(body.createdAt), updatedAt: new Date(body.createdAt) } : {}),
  }).returning()
  return message
})
