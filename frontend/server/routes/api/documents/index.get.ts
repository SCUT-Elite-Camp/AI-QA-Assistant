import { defineHandler } from 'nitro'
import { accessBackend, requireEnabledActor } from '../../../utils/sourceAccess'

export default defineHandler(async (event) => {
  const response = await accessBackend(await requireEnabledActor(event), 'documents')
  const payload = await response.json() as any
  const documents = Array.isArray(payload) ? payload : payload.documents || payload.items || []
  return documents.map((doc: any) => ({ ...doc, docId: doc.doc_id || doc.id,
    fileName: doc.title, fileType: 'CONFLUENCE', sourceUrl: doc.source_url || doc.address,
    lastUpdated: doc.last_updated, chunkCount: doc.chunk_count ?? 0, charCount: doc.char_count ?? 0 }))
})
