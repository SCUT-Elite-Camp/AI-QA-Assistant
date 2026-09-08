import { eq } from 'drizzle-orm'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables } from '../../../utils/drizzle'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const { researchId, query } = await readValidatedBody(event, z.object({
    researchId: z.string().regex(/^research-[a-zA-Z0-9]+$/),
    query: z.string().trim().min(1).max(4000),
  }).parse)
  const db = useDrizzle()
  const existing = await db.query.chats.findFirst({
    where: eq(tables.chats.id, researchId),
  })
  if (existing) return existing

  const title = query.length > 28 ? `${query.slice(0, 28)}...` : query
  const [chat] = await db.insert(tables.chats).values({
    id: researchId,
    title,
    userId: session.data.user?.id || session.id!,
  }).returning()
  if (!chat) throw new HTTPError({ statusCode: 500, statusMessage: 'Failed to register research conversation' })

  await db.insert(tables.messages).values({
    chatId: researchId,
    role: 'user',
    parts: [{ type: 'text', text: query }],
  })
  return chat
})
