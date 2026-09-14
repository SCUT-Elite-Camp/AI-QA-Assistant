import fs from 'node:fs'
import path from 'node:path'
import { defineHandler } from 'nitro'

interface CatalogDocument {
  doc_id: string
  title: string
  source_type: string
}

export default defineHandler((): CatalogDocument[] => {
  const documentsDir = path.resolve(process.cwd(), '../data-persistence/data/documents')
  if (!fs.existsSync(documentsDir)) return []

  return fs.readdirSync(documentsDir, { withFileTypes: true })
    .filter(entry => entry.isFile() && entry.name.endsWith('.json'))
    .flatMap((entry) => {
      try {
        const filePath = path.join(documentsDir, entry.name)
        const document = JSON.parse(fs.readFileSync(filePath, 'utf-8'))
        const docId = String(document.doc_id || path.basename(entry.name, '.json'))
        const sourceType = String(document.source_type || 'local_document')
        if (sourceType === 'web_page' || docId.startsWith('web-')) return []
        return [{ doc_id: docId, title: String(document.title || docId), source_type: sourceType }]
      } catch {
        return []
      }
    })
    .sort((left, right) => left.title.localeCompare(right.title, 'zh-CN'))
})
