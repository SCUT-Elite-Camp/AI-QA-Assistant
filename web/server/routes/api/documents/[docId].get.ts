import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getValidatedRouterParams } from 'nitro/h3'
import fs from 'fs'
import path from 'path'

export default defineHandler(async (event) => {
  const { docId } = await getValidatedRouterParams(event, z.object({
    docId: z.string()
  }).parse)

  // Find document JSON in data-persistence/data/documents/
  const docDir = path.resolve(process.cwd(), '../data-persistence/data/documents')
  const filePath = path.join(docDir, `${docId}.json`)

  if (!fs.existsSync(filePath)) {
    throw new HTTPError({ statusCode: 404, statusMessage: `Document file ${docId} not found` })
  }

  try {
    const raw = fs.readFileSync(filePath, 'utf-8')
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
})
