import fs from 'node:fs'
import path from 'node:path'
import { useDrizzle, tables, eq } from './drizzle'

export interface KnowledgeDocInfo {
  docId: string
  title: string
  spaceKey: string
  sourceUrl?: string
  lastUpdated?: string
  content?: string
}

/**
 * 从 data-persistence/data/documents 中同步知识库文档到 SQLite 的 files 表
 */
export async function syncKnowledgeBaseDocuments(): Promise<number> {
  const db = useDrizzle()
  const possiblePaths = [
    path.resolve(process.cwd(), '..', 'data-persistence', 'data', 'documents'),
    path.resolve(process.cwd(), 'data-persistence', 'data', 'documents'),
  ]

  let docsDir = possiblePaths.find(p => fs.existsSync(p))
  if (!docsDir) {
    return 0
  }

  const jsonFiles = fs.readdirSync(docsDir).filter(f => f.endsWith('.json'))
  if (!jsonFiles.length) return 0

  let count = 0
  for (const filename of jsonFiles) {
    try {
      const fullPath = path.join(docsDir, filename)
      const raw = fs.readFileSync(fullPath, 'utf8')
      const doc = JSON.parse(raw)

      const docId = doc.doc_id || path.basename(filename, '.json')
      const title = doc.title || docId
      const spaceKey = doc.space || doc.space_key || 'RAG'
      const content = doc.content || ''
      const size = Buffer.byteLength(content, 'utf8')
      const storagePath = `confluence://${spaceKey}/${docId}`
      const createdAt = doc.last_updated ? new Date(doc.last_updated) : new Date()

      const [existing] = await db.select({ id: tables.files.id })
        .from(tables.files)
        .where(eq(tables.files.docId, docId))

      if (!existing) {
        await db.insert(tables.files).values({
          id: `kb_${docId}`,
          userId: 'dev-user',
          name: title,
          originalName: title,
          mimeType: 'text/markdown',
          size,
          storagePath,
          visibility: 'shared',
          docId,
          createdAt,
        })
      } else {
        await db.update(tables.files).set({
          name: title,
          originalName: title,
          size,
          storagePath,
        }).where(eq(tables.files.docId, docId))
      }
      count++
    } catch (e) {
      // 忽略单个文档解析异常
    }
  }

  return count
}
