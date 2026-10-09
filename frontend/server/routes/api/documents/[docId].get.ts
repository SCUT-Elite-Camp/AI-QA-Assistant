import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import fs from 'fs'
import path from 'path'

export default defineHandler(async (event) => {
  const { docId } = await getValidatedRouterParams(event, z.object({
    docId: z.string()
  }).parse)

  // 1. Direct match by filename
  const docDir = path.resolve(process.cwd(), '../data-persistence/data/documents')
  const directPath = path.join(docDir, `${docId}.json`)

  if (fs.existsSync(directPath)) {
    try {
      const raw = fs.readFileSync(directPath, 'utf-8')
      const json = JSON.parse(raw)
      return {
        doc_id: json.doc_id || docId,
        title: json.title || `Document ${docId}`,
        content: json.content || '',
        chunks: json.chunks || [],
        address: json.address || '',
        last_updated: json.last_updated || ''
      }
    } catch (err: any) {
      throw new HTTPError({ statusCode: 500, statusMessage: `Error reading document: ${err.message}` })
    }
  }

  // 2. Search by title or doc_id inside data-persistence/data/documents
  if (fs.existsSync(docDir)) {
    const files = fs.readdirSync(docDir)
    for (const f of files) {
      if (!f.endsWith('.json')) continue
      try {
        const fullPath = path.join(docDir, f)
        const raw = fs.readFileSync(fullPath, 'utf-8')
        const json = JSON.parse(raw)
        if (
          json.doc_id === docId ||
          json.title === docId ||
          (json.title && json.title.toLowerCase() === docId.toLowerCase()) ||
          f === `${docId}.json`
        ) {
          return {
            doc_id: json.doc_id || docId,
            title: json.title || `Document ${docId}`,
            content: json.content || '',
            chunks: json.chunks || [],
            address: json.address || '',
            last_updated: json.last_updated || ''
          }
        }
      } catch {
        // continue
      }
    }
  }

  throw new HTTPError({ statusCode: 404, statusMessage: `Document ${docId} not found` })
})
