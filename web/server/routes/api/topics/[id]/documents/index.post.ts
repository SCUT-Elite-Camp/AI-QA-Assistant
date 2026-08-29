import fs from 'fs'
import path from 'path'
import crypto from 'crypto'
import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams, readValidatedBody } from 'nitro/h3'
import { useDrizzle, tables, eq } from '../../../../../utils/drizzle'
import { syncTopicToDisk, ensureTopicDir } from '../../../../../utils/topicStorage'

export default defineHandler(async (event) => {
  const { id } = await getValidatedRouterParams(event, z.object({
    id: z.string()
  }).parse)

  const { title, content } = await readValidatedBody(event, z.object({
    title: z.string(),
    content: z.string()
  }).parse)

  const db = useDrizzle()

  const topic = await db.query.topics.findFirst({
    where: eq(tables.topics.id, id)
  })

  if (!topic) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Topic space not found' })
  }

  const docId = crypto.randomUUID()

  // Insert into SQLite DB
  const [newDoc] = await db.insert(tables.topicDocuments).values({
    docId,
    topicId: id,
    title: title.trim(),
    content,
    chunkCount: 1,
    isRemoved: false
  }).returning()

  // Save physical file into data-persistence/data/topics/<topicId>/documents/
  try {
    const topicDir = ensureTopicDir(id)
    const docsFolder = path.join(topicDir, 'documents')
    if (!fs.existsSync(docsFolder)) {
      fs.mkdirSync(docsFolder, { recursive: true })
    }
    const safeTitle = title.replace(/[^a-zA-Z0-9_\-\.\u4e00-\u9fa5]/g, '_')
    const filePath = path.join(docsFolder, `${docId}_${safeTitle}`)
    fs.writeFileSync(filePath, content, 'utf-8')
  } catch (err) {
    console.error('[TopicDocStorage] Failed to write doc to persistence folder:', err)
  }

  // Sync topic metadata and docs pool to disk
  const allDocs = await db.query.topicDocuments.findMany({
    where: eq(tables.topicDocuments.topicId, id)
  })
  syncTopicToDisk(id, topic, topic.soulContent, allDocs.filter(d => !d.isRemoved))

  return newDoc
})
