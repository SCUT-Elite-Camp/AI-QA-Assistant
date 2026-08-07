import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { syncTopicToDisk } from '../../../utils/topicStorage'


export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const body = await readValidatedBody(event, z.object({
    title: z.string().optional(),
    weightMode: z.enum(['deeper', 'auto', 'wider']).optional(),
    soulContent: z.string().optional(),
    tags: z.array(z.string()).optional()
  }).parse)

  const db = useDrizzle()

  const topic = await db.query.topics.findFirst({
    where: eq(tables.topics.id, id)
  })

  if (!topic) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Topic space not found' })
  }

  const updateData: Record<string, any> = {}
  if (body.title !== undefined) updateData.title = body.title
  if (body.weightMode !== undefined) updateData.weightMode = body.weightMode
  if (body.soulContent !== undefined) updateData.soulContent = body.soulContent
  if (body.tags !== undefined) updateData.tags = body.tags

  const [updated] = await db.update(tables.topics)
    .set(updateData)
    .where(eq(tables.topics.id, id))
    .returning()

  // Sync updated topic info and soul.md to disk folder in data-persistence/data/topics/<id>/
  const docs = await db.query.topicDocuments.findMany({
    where: eq(tables.topicDocuments.topicId, id)
  })
  syncTopicToDisk(updated.id, updated, updated.soulContent, docs)

  return updated
})

