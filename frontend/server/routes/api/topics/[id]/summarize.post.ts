import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'
import { requestTopicSummarizerFromPersistence } from '../../../../utils/soul'
import { syncTopicToDisk } from '../../../../utils/topicStorage'
import { requireCsrf, requireTopicRole } from '../../../../utils/attachmentAuth'
import { assertDerivedSources, requireEnabledActor } from '../../../../utils/sourceAccess'
import { discussionEvidence, readableTopic } from '../../../../utils/topicEvidence'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const { id } = await getValidatedRouterParams(event, z.object({ id: z.string() }).parse)
  const { userId } = await requireTopicRole(event, id, 'editor')
  const db = useDrizzle()
  const topic = await db.query.topics.findFirst({ where: eq(tables.topics.id, id),
    with: { chats: { with: { messages: true } } } })
  if (!topic) throw new HTTPError({ statusCode: 404, statusMessage: 'topic_not_found' })
  const messages = topic.chats.flatMap(chat => chat.messages.filter(m => m.historyRevision === chat.historyRevision))
  const { text, proof } = await discussionEvidence(userId, messages)
  const visible = await readableTopic(userId, topic)
  // Rebuild from currently readable messages; do not silently load old disk Soul.
  const result = await requestTopicSummarizerFromPersistence(id, text, visible.title, {}, { userId, proof })
  if (!result) throw new HTTPError({ statusCode: 503, statusMessage: 'topic_summary_unavailable' })
  await requireEnabledActor(event)
  await requireTopicRole(event, id, 'editor')
  await assertDerivedSources(userId, proof)
  const [updated] = await db.update(tables.topics).set({ title: result.title,
    soulContent: result.soulContent, description: result.description || '', tags: result.tags || [],
    evidenceProvenance: proof, status: 'ready' }).where(eq(tables.topics.id, id)).returning()
  syncTopicToDisk(id, updated, updated.soulContent, [])
  return updated
})
