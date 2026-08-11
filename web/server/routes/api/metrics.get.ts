import { defineHandler } from 'nitro'
import { getMetrics } from '../../utils/metrics'
import { useDrizzle, tables } from '../../utils/drizzle'
import { $fetch } from 'ofetch'
import fs from 'fs'
import path from 'path'

/**
 * GET /api/metrics
 * 暴露服务端可观测指标、服务健康状态、数据库统计与已入库文档列表。
 */
export default defineHandler(async () => {
  const metrics = getMetrics()

  // Check Agent Backend health (FastAPI port 8000)
  let agentHealth = 'offline'
  let vectorBackend = 'milvus'
  try {
    const healthResp: any = await $fetch('http://127.0.0.1:8000/health', { timeout: 1500 }).catch(() => null)
    if (healthResp) {
      agentHealth = healthResp.status === 'ok' ? 'healthy' : 'degraded'
      vectorBackend = healthResp.retrieval_backend || 'milvus'
    }
  } catch (e) {
    agentHealth = 'offline'
  }

  // Scan indexed JSON documents in data-persistence/data/documents
  const docDir = path.resolve(process.cwd(), '../data-persistence/data/documents')
  let indexedDocs: any[] = []
  if (fs.existsSync(docDir)) {
    const files = fs.readdirSync(docDir).filter(f => f.endsWith('.json') && !f.startsWith('.'))
    indexedDocs = files.map(file => {
      try {
        const filePath = path.join(docDir, file)
        const stat = fs.statSync(filePath)
        const raw = fs.readFileSync(filePath, 'utf-8')
        const json = JSON.parse(raw)
        const contentStr = json.content || (json.chunks || []).map((c: any) => c.text || '').join('\n')
        return {
          doc_id: json.doc_id || file.replace('.json', ''),
          title: json.title || file.replace('.json', ''),
          last_updated: json.last_updated || json.metadata?.last_updated || stat.mtime.toISOString(),
          char_count: contentStr.length || 0,
          space: json.space || json.metadata?.space_key || ''
        }
      } catch (e) {
        return null
      }
    }).filter(Boolean)
  }

  // Count SQLite topics & documents
  let topicsCount = 0
  try {
    const db = useDrizzle()
    const topics = await db.select().from(tables.topics).catch(() => [])
    topicsCount = topics.length
  } catch (e) {
    // Ignore
  }

  return {
    ...metrics,
    services: {
      agentApi: agentHealth,
      webServer: 'healthy',
      vectorDb: vectorBackend,
      database: 'healthy',
    },
    counts: {
      topics: topicsCount,
      documents: indexedDocs.length,
    },
    indexedDocs
  }
})

