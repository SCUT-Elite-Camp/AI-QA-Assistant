import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useUserSession } from '../../utils/session'
import { useDrizzle, tables } from '../../utils/drizzle'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)

  const { input } = await readValidatedBody(event, z.object({
    input: z.string()
  }).parse)
  const db = useDrizzle()

  const cleanInput = input.trim()
  const initialTitle = cleanInput.length > 20 ? cleanInput.slice(0, 20) + '...' : (cleanInput || '新对话')

  const [chat] = await db.insert(tables.chats).values({
    title: initialTitle,
    userId: session.data.user?.id || session.id!
  }).returning()
  if (!chat) {
    throw new HTTPError({ statusCode: 500, statusMessage: 'Failed to create chat' })
  }

  await db.insert(tables.messages).values({
    chatId: chat.id,
    role: 'user',
    parts: [{ type: 'text', text: input }]
  })

  return chat
})
