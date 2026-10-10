import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { readValidatedBody } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { requireCsrf, requirePrincipal, requireTopicRole } from '../../../utils/attachmentAuth'
import { requestTopicSummarizerFromPersistence } from '../../../utils/soul'
import { syncTopicToDisk, syncAllTopicDocuments } from '../../../utils/topicStorage'
import { discussionEvidence, readableTopic } from '../../../utils/topicEvidence'
import { assertDerivedSources, authoredProvenance } from '../../../utils/sourceAccess'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const userId = await requirePrincipal(event)
  const body = await readValidatedBody(event, z.object({ chatId: z.string().optional(), title: z.string().max(200).optional() }).parse)
  const db = useDrizzle()
  let chat = body.chatId ? await db.query.chats.findFirst({ where: eq(tables.chats.id, body.chatId), with: { messages: true } }) : undefined
  if (body.chatId && !chat) throw new HTTPError({ statusCode: 404, statusMessage: 'chat_not_found' })
  if (chat?.topicId) {
    await requireTopicRole(event, chat.topicId, 'viewer')
    const topic = await db.query.topics.findFirst({ where: eq(tables.topics.id, chat.topicId) })
    if (!topic) throw new HTTPError({ statusCode: 404, statusMessage: 'topic_not_found' })
    return readableTopic(userId, topic)
  }
  if (chat && chat.userId !== userId) throw new HTTPError({ statusCode: 404, statusMessage: 'chat_not_found' })
  const title = body.title?.trim() || 'Topic Workspace'
  if (!chat) {
    const [created] = await db.insert(tables.chats).values({ userId, title, evidenceProvenance: authoredProvenance() }).returning()
    chat = { ...created, messages: [] }
  }
  const messages = chat.messages.filter(m => m.historyRevision === chat!.historyRevision)
  const discussion = messages.length ? await discussionEvidence(userId, messages) : { text: title, proof: authoredProvenance() }
  const [topic] = await db.insert(tables.topics).values({
    title,
    mainChatId: chat.id,
    soulContent: '',
    tags: [],
    status: 'generating',
    evidenceProvenance: authoredProvenance(),
  }).returning()
  await db.insert(tables.topicMembers).values({ topicId: topic.id, userId, role: 'owner' }).onConflictDoNothing()
  await db.update(tables.chats).set({ topicId: topic.id }).where(eq(tables.chats.id, chat.id))
  await syncAllTopicDocuments(db, topic.id)
  void requestTopicSummarizerFromPersistence(topic.id, discussion.text, body.title, {}, { userId, proof: discussion.proof }).then(async result => {
    if (!result) throw new Error('topic_summary_unavailable')
    await requireTopicRole(event, topic.id, 'editor')
    await assertDerivedSources(userId, discussion.proof)
    const [updated] = await db.update(tables.topics).set({ title: result.title, description: result.description || '',
      soulContent: result.soulContent, tags: result.tags || [], evidenceProvenance: discussion.proof, status: 'ready',
    }).where(eq(tables.topics.id, topic.id)).returning()
    syncTopicToDisk(topic.id, updated, updated.soulContent, [])
  }).catch(async () => {
    await db.update(tables.topics).set({ status: 'ready' }).where(eq(tables.topics.id, topic.id))
  })
  return topic
})
