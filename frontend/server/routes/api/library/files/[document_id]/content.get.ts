import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { and, eq, tables, useDrizzle } from '../../../../../utils/drizzle'
import { attachmentServiceFetch } from '../../../../../utils/attachmentService'
import { requireLibraryDocument } from '../../../../../utils/library'

export default defineHandler(async (event) => {
  const documentId = getRouterParam(event, 'document_id') || ''
  const { document } = await requireLibraryDocument(event, documentId)
  if (!document.activeVersionId) throw new HTTPError({ statusCode: 409, statusMessage: 'library_document_not_ready' })
  const version = await useDrizzle().query.documentVersions.findFirst({
    where: and(
      eq(tables.documentVersions.id, document.activeVersionId),
      eq(tables.documentVersions.documentId, document.id),
    )
  })
  if (!version) throw new HTTPError({ statusCode: 404, statusMessage: 'library_version_not_found' })
  const response = await attachmentServiceFetch(`/v1/attachments/${version.storageRef}/content`)
  if (!response.ok || !response.body) throw new HTTPError({ statusCode: response.status, statusMessage: 'library_content_unavailable' })
  return new Response(response.body, { status: response.status, headers: {
    'content-type': response.headers.get('content-type') || document.mimeType,
    'content-disposition': response.headers.get('content-disposition') || 'inline',
    'cache-control': 'private, no-store'
  } })
})
