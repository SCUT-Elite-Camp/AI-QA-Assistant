import fs from 'fs'
import path from 'path'
import { logger } from './logger'
import { tables, eq, and, inArray } from './drizzle'

function getTopicsDir(): string {
  let cwd = process.cwd()
  if (cwd.endsWith('web') || cwd.endsWith('web/')) {
    cwd = path.resolve(cwd, '..')
  }
  const topicsDir = path.join(cwd, 'data-persistence', 'data', 'topics')
  if (!fs.existsSync(topicsDir)) {
    fs.mkdirSync(topicsDir, { recursive: true })
  }
  return topicsDir
}

export function ensureTopicDir(topicId: string): string {
  const topicsDir = getTopicsDir()
  const dirPath = path.join(topicsDir, topicId)
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true })
  }
  const docsFolder = path.join(dirPath, 'documents')
  if (!fs.existsSync(docsFolder)) {
    fs.mkdirSync(docsFolder, { recursive: true })
  }
  return dirPath
}

export function syncTopicToDisk(
  topicId: string,
  topicInfo: {
    id: string
    title: string
    mainChatId: string
    weightMode: string
    consecutiveNoNewDocsCount: number
    createdAt?: any
    updatedAt?: any
  },
  soulContent: string,
  documentsPool: any[] = []
) {
  try {
    const topicDir = ensureTopicDir(topicId)

    // 1. Write soul.md
    const soulPath = path.join(topicDir, 'soul.md')
    fs.writeFileSync(soulPath, soulContent || '', 'utf-8')

    // 2. Write topic_info.json
    const infoPath = path.join(topicDir, 'topic_info.json')
    fs.writeFileSync(
      infoPath,
      JSON.stringify(
        {
          ...topicInfo,
          last_synced_at: new Date().toISOString()
        },
        null,
        2
      ),
      'utf-8'
    )

    // 3. Write documents_pool.json
    const docsPath = path.join(topicDir, 'documents_pool.json')
    fs.writeFileSync(
      docsPath,
      JSON.stringify(documentsPool || [], null, 2),
      'utf-8'
    )

    logger.info(`[TopicStorage] Synced topic ${topicId} to ${topicDir}`)
  } catch (err) {
    logger.error(`[TopicStorage] Failed to sync topic ${topicId}:`, err)
  }
}

export function loadTopicFromDisk(topicId: string) {
  try {
    const topicsDir = getTopicsDir()
    const topicDir = path.join(topicsDir, topicId)
    if (!fs.existsSync(topicDir)) return null

    const soulPath = path.join(topicDir, 'soul.md')
    const soulContent = fs.existsSync(soulPath) ? fs.readFileSync(soulPath, 'utf-8') : ''

    const infoPath = path.join(topicDir, 'topic_info.json')
    const topicInfo = fs.existsSync(infoPath) ? JSON.parse(fs.readFileSync(infoPath, 'utf-8')) : null

    const docsPath = path.join(topicDir, 'documents_pool.json')
    const documentsPool = fs.existsSync(docsPath) ? JSON.parse(fs.readFileSync(docsPath, 'utf-8')) : []

    return {
      topicInfo,
      soulContent,
      documentsPool
    }
  } catch (err) {
    logger.error(`[TopicStorage] Failed to load topic ${topicId} from disk:`, err)
    return null
  }
}

export function getTopicDocumentsFromDisk(topicId: string): any[] {
  try {
    const topicDir = ensureTopicDir(topicId)
    const docsPoolPath = path.join(topicDir, 'documents_pool.json')
    let pool: any[] = []
    if (fs.existsSync(docsPoolPath)) {
      try {
        pool = JSON.parse(fs.readFileSync(docsPoolPath, 'utf-8')) || []
      } catch (e) {}
    }

    const docMap = new Map<string, any>()
    for (const item of pool) {
      if (item && item.docId) {
        docMap.set(item.docId, item)
      }
    }

    // Scan physical files in data-persistence/data/topics/<topicId>/documents/
    const docsFolder = path.join(topicDir, 'documents')
    if (fs.existsSync(docsFolder)) {
      const files = fs.readdirSync(docsFolder)
      for (const fileName of files) {
        const filePath = path.join(docsFolder, fileName)
        const stat = fs.statSync(filePath)
        if (stat.isFile()) {
          const underscoreIdx = fileName.indexOf('_')
          const docId = underscoreIdx > 0 ? fileName.slice(0, underscoreIdx) : fileName
          const displayTitle = underscoreIdx > 0 ? fileName.slice(underscoreIdx + 1) : fileName

          if (!docMap.has(docId)) {
            const rawContent = fs.readFileSync(filePath, 'utf-8')
            docMap.set(docId, {
              docId,
              title: displayTitle,
              content: rawContent,
              snippet: rawContent.slice(0, 150),
              recallCount: 1,
              lastRecalledAt: stat.mtime.toISOString(),
              isRemoved: false
            })
          }
        }
      }
    }

    return Array.from(docMap.values()).filter(d => !d.isRemoved)
  } catch (err) {
    logger.error(`[TopicStorage] Error reading documents from disk for topic ${topicId}:`, err)
    return []
  }
}

export async function copyChatCitationsToTopic(db: any, chat: any, topicId: string) {
  if (!chat || !chat.messages || !chat.messages.length) return

  try {
    const topicDir = ensureTopicDir(topicId)
    const docsFolder = path.join(topicDir, 'documents')

    const citationsToSave: any[] = []

    for (const msg of chat.messages) {
      const parts = (msg.parts || []) as any[]
      for (const part of parts) {
        const output = part.output || part.result || part.toolInvocation?.result || part.toolInvocation?.output
        if (Array.isArray(output)) {
          for (const item of output) {
            if (item && (item.doc_id || item.title || item.chunk_text || item.snippet)) {
              citationsToSave.push(item)
            }
          }
        }
      }
    }

    if (citationsToSave.length > 0) {
      for (const cit of citationsToSave) {
        const docId = cit.doc_id || `doc_${Date.now()}`
        const title = cit.title || cit.doc_id || 'Retrieved Document'
        const snippet = cit.chunk_text || cit.snippet || ''

        const existingDoc = await db.query.topicDocuments.findFirst({
          where: and(
            eq(tables.topicDocuments.topicId, topicId),
            eq(tables.topicDocuments.docId, docId)
          )
        })

        if (existingDoc) {
          await db.update(tables.topicDocuments).set({
            recallCount: existingDoc.recallCount + 1,
            lastRecalledAt: new Date(),
            snippet: snippet || existingDoc.snippet
          }).where(eq(tables.topicDocuments.id, existingDoc.id))
        } else {
          await db.insert(tables.topicDocuments).values({
            topicId,
            docId,
            title,
            sourceUrl: cit.source_url || null,
            snippet,
            recallCount: 1,
            score: cit.score ? Math.round(cit.score * 100) : null
          })
        }

        // Save physical file directly into data-persistence/data/topics/<topicId>/documents/
        try {
          const safeTitle = title.replace(/[^a-zA-Z0-9_\-\.\u4e00-\u9fa5]/g, '_')
          const filePath = path.join(docsFolder, `${docId}_${safeTitle}.txt`)
          const fileText = `Title: ${title}\nSource: ${cit.source_url || 'Parent Chat RAG'}\nScore: ${cit.score || ''}\n\nContent:\n${snippet}`
          fs.writeFileSync(filePath, fileText, 'utf-8')
        } catch (fErr) {
          console.error('[TopicStorage] Error writing copied citation file:', fErr)
        }
      }

      const latestTopic = await db.query.topics.findFirst({ where: eq(tables.topics.id, topicId) })
      const latestDocs = await db.query.topicDocuments.findMany({ where: eq(tables.topicDocuments.topicId, topicId) })
      if (latestTopic) {
        syncTopicToDisk(latestTopic.id, latestTopic, latestTopic.soulContent, latestDocs)
      }
    }
  } catch (err) {
    console.error('[TopicStorage] copyChatCitationsToTopic failed:', err)
  }
}

export function deleteTopicFromDisk(topicId: string) {
  try {
    const topicsDir = getTopicsDir()
    const topicDir = path.join(topicsDir, topicId)
    if (fs.existsSync(topicDir)) {
      fs.rmSync(topicDir, { recursive: true, force: true })
      logger.info(`[TopicStorage] Deleted topic folder ${topicDir}`)
    }
  } catch (err) {
    logger.error(`[TopicStorage] Failed to delete topic folder ${topicId}:`, err)
  }
}

export function extractCitationsFromParts(parts: any): any[] {
  if (!parts) return []
  let p = parts
  if (typeof parts === 'string') {
    try { p = JSON.parse(parts) } catch { return [] }
  }
  if (!Array.isArray(p)) return []

  const citations: any[] = []
  for (const item of p) {
    if (!item) continue
    const output = item.output || item.result || item.data
    if (output) {
      const arr = Array.isArray(output) ? output : [output]
      for (const cit of arr) {
        if (cit && typeof cit === 'object' && (cit.doc_id || cit.docId || cit.title)) {
          citations.push({
            doc_id: cit.doc_id || cit.docId || `doc_${Date.now()}`,
            title: cit.title || cit.doc_id || cit.docId || 'Retrieved Document',
            source_url: cit.source_url || cit.sourceUrl || null,
            snippet: cit.chunk_text || cit.snippet || cit.content || '',
            score: cit.score ?? null
          })
        }
      }
    }
  }
  return citations
}

export async function syncAllTopicDocuments(db: any, topicId: string) {
  if (!topicId) return []
  try {
    const topicChats = await db.query.chats.findMany({
      where: eq(tables.chats.topicId, topicId)
    })
    const chatIds = topicChats.map((c: any) => c.id)
    if (!chatIds.length) return []

    const assistantMessages = await db.query.messages.findMany({
      where: and(
        inArray(tables.messages.chatId, chatIds),
        eq(tables.messages.role, 'assistant')
      )
    })

    const foundCitations: any[] = []
    for (const msg of assistantMessages) {
      const cits = extractCitationsFromParts(msg.parts)
      for (const c of cits) {
        foundCitations.push(c)
      }
    }

    const topicDir = ensureTopicDir(topicId)
    const docsFolder = path.join(topicDir, 'documents')
    if (!fs.existsSync(docsFolder)) {
      fs.mkdirSync(docsFolder, { recursive: true })
    }

    for (const cit of foundCitations) {
      const docId = cit.doc_id
      const title = cit.title || docId
      const snippet = cit.snippet || ''

      const existingDoc = await db.query.topicDocuments.findFirst({
        where: and(
          eq(tables.topicDocuments.topicId, topicId),
          eq(tables.topicDocuments.docId, docId)
        )
      })

      if (existingDoc) {
        if (!existingDoc.isRemoved) {
          await db.update(tables.topicDocuments).set({
            recallCount: existingDoc.recallCount + 1,
            lastRecalledAt: new Date(),
            snippet: snippet || existingDoc.snippet
          }).where(eq(tables.topicDocuments.id, existingDoc.id))
        }
      } else {
        await db.insert(tables.topicDocuments).values({
          topicId,
          docId,
          title,
          sourceUrl: cit.source_url || null,
          snippet,
          recallCount: 1,
          score: cit.score ? Math.round(cit.score * 100) : null,
          isUserUploaded: false
        }).onConflictDoNothing()
      }

      try {
        const safeTitle = title.replace(/[^a-zA-Z0-9_\-\.\u4e00-\u9fa5]/g, '_')
        const filePath = path.join(docsFolder, `${docId}_${safeTitle}.txt`)
        const fileText = `Title: ${title}\nSource: ${cit.source_url || 'RAG Retrieval'}\nScore: ${cit.score || ''}\n\nContent:\n${snippet}`
        fs.writeFileSync(filePath, fileText, 'utf-8')
      } catch (fErr) {}
    }

    const latestTopic = await db.query.topics.findFirst({ where: eq(tables.topics.id, topicId) })
    const latestDocs = await db.query.topicDocuments.findMany({ where: eq(tables.topicDocuments.topicId, topicId) })
    if (latestTopic) {
      syncTopicToDisk(latestTopic.id, latestTopic, latestTopic.soulContent, latestDocs)
    }

    return latestDocs || []
  } catch (err) {
    logger.error(`[TopicStorage] Failed to sync all topic documents for ${topicId}:`, err)
    return []
  }
}
