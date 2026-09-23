import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'
import { requestTopicSummarizerFromPersistence } from '../../../../utils/soul'
import { saveFavoriteToDisk, removeFavoriteFromDisk } from '../../../../utils/favoriteStorage'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { isFavorite, suggestionText } = await readValidatedBody(event, z.object({
    isFavorite: z.boolean().optional(),
    suggestionText: z.string().optional()
  }).parse)

  const db = useDrizzle()

  const message = await db.query.messages.findFirst({
    where: eq(tables.messages.id, id),
    with: { chat: true }
  })

  if (!message) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Message not found' })
  }

  const updateFields: Record<string, any> = {}
  if (isFavorite !== undefined) updateFields.isFavorite = isFavorite
  if (suggestionText !== undefined) updateFields.suggestionText = suggestionText

  await db.update(tables.messages)
    .set(updateFields)
    .where(eq(tables.messages.id, id))

  await db.insert(tables.messageFeedbacks).values({
    chatId: message.chatId,
    messageId: message.id,
    isFavorite: isFavorite ?? false,
    suggestionText: suggestionText || null
  })

  // ── Persist to data-persistence disk layer ──────────────────────────────
  if (isFavorite !== undefined) {
    const chatTitle = (message.chat as any)?.title || 'Untitled'
    const messageText = ((message.parts as any[])?.[0]?.text || '').slice(0, 500)

    if (isFavorite) {
      saveFavoriteToDisk({
        chatId: message.chatId,
        chatTitle,
        messageId: message.id,
        messageRole: message.role,
        messageText,
        favoritedAt: new Date().toISOString(),
        suggestionText: suggestionText
      })
    } else {
      removeFavoriteFromDisk(message.chatId, message.id)
    }
  }
  // ────────────────────────────────────────────────────────────────────────

  // If chat belongs to a topic, trigger incremental Soul update in background
  if (message.chat?.topicId) {
    const topic = await db.query.topics.findFirst({
      where: eq(tables.topics.id, message.chat.topicId)
    })
    if (topic) {
      const qText = message.role === 'assistant' ? '解答反馈' : '提问反馈'
      const aText = (message.parts as any)?.[0]?.text || ''
      
      const discussion = [qText, aText, suggestionText || ''].filter(Boolean).join('\n')
      requestTopicSummarizerFromPersistence(topic.id, discussion, topic.title, {
        title: topic.title,
        description: topic.description,
        soulContent: topic.soulContent,
        tags: topic.tags,
      }).then(async (summary) => {
        if (summary) {
          await db.update(tables.topics).set({
            title: summary.title,
            description: summary.description,
            soulContent: summary.soulContent,
            tags: summary.tags,
          }).where(eq(tables.topics.id, topic.id))
        }
      }).catch(err => console.warn('[SoulUpdateError]', err))
    }
  }

  return { status: 'ok', messageId: id, isFavorite, suggestionText }
})
