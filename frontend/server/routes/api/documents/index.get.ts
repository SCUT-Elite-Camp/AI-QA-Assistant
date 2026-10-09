import fs from 'fs'
import path from 'path'
import { defineHandler } from 'nitro'

export default defineHandler(async () => {
  const docDir = path.resolve(process.cwd(), '../data-persistence/data/documents')
  const rawsDir = path.resolve(process.cwd(), '../data-persistence/data/raws')

  const docMap = new Map<string, any>()

  // 1. Read JSON documents from data-persistence/data/documents/
  if (fs.existsSync(docDir)) {
    const files = fs.readdirSync(docDir)
    for (const f of files) {
      if (!f.endsWith('.json') || f.endsWith('.gitkeep')) continue
      try {
        const fullPath = path.join(docDir, f)
        const stat = fs.statSync(fullPath)
        const raw = fs.readFileSync(fullPath, 'utf-8')
        const json = JSON.parse(raw)

        const docId = json.doc_id || path.basename(f, '.json')
        const title = json.title || docId
        const content = json.content || ''
        const chunks = json.chunks || []
        const lastUpdated = json.last_updated || stat.mtime.toISOString()
        const sourceUrl = json.source_url || json.address || title

        let ext = path.extname(sourceUrl).toLowerCase()
        if (!ext && title.includes('.')) {
          ext = path.extname(title).toLowerCase()
        }
        if (!ext) ext = '.json'

        docMap.set(docId, {
          docId,
          title,
          fileName: path.basename(sourceUrl) || `${title}${ext}`,
          fileType: ext.replace('.', '').toUpperCase() || 'JSON',
          chunkCount: chunks.length,
          charCount: content.length,
          lastUpdated,
          sourceUrl
        })
      } catch (e) {
        console.warn(`[documents.get] Failed to parse ${f}:`, e)
      }
    }
  }

  // 2. Also check raw files in data-persistence/data/raws/
  if (fs.existsSync(rawsDir)) {
    const rawFiles = fs.readdirSync(rawsDir)
    for (const rf of rawFiles) {
      if (rf.endsWith('.gitkeep')) continue
      const fullPath = path.join(rawsDir, rf)
      const stat = fs.statSync(fullPath)
      const ext = path.extname(rf).toLowerCase()
      const docId = `raw_${rf.replace(/[^a-zA-Z0-9_-]/g, '_')}`

      if (!docMap.has(docId)) {
        docMap.set(docId, {
          docId,
          title: rf,
          fileName: rf,
          fileType: ext.replace('.', '').toUpperCase() || 'FILE',
          chunkCount: 1,
          charCount: stat.size,
          lastUpdated: stat.mtime.toISOString(),
          sourceUrl: rf
        })
      }
    }
  }

  const docs = Array.from(docMap.values())
  docs.sort((a, b) => new Date(b.lastUpdated).getTime() - new Date(a.lastUpdated).getTime())

  return docs
})
