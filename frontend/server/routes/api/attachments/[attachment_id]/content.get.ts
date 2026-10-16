import { defineHandler, HTTPError } from 'nitro'
import { getQuery, getRouterParam } from 'nitro/h3'
import { requireAttachmentAccess } from '../../../../utils/attachmentAccess'
import { attachmentServiceFetch } from '../../../../utils/attachmentService'

export default defineHandler(async (event) => {
  const id = getRouterParam(event, 'attachment_id') || ''
  const { attachment } = await requireAttachmentAccess(event, id)
  const query = getQuery(event)
  const params = new URLSearchParams()
  if (query.expected_hash != null || query.expected_version != null) {
    if (String(query.expected_hash || '') !== attachment.sha256 || String(query.expected_version || '') !== String(attachment.evidenceVersion)) {
      throw new HTTPError({ statusCode: 409, statusMessage: 'source_evidence_changed' })
    }
    params.set('expected_hash', String(query.expected_hash))
    params.set('expected_version', String(query.expected_version))
  }
  const suffix = params.size ? `?${params}` : ''
  const response = await attachmentServiceFetch(`/v1/attachments/${id}/content${suffix}`)
  if (!response.ok || !response.body) throw new HTTPError({ statusCode: response.status, statusMessage: 'attachment_content_unavailable' })
  return new Response(response.body, { status: response.status, headers: {
    'content-type': response.headers.get('content-type') || 'application/octet-stream',
    'content-disposition': response.headers.get('content-disposition') || 'inline',
    'cache-control': 'private, no-store'
  } })
})
