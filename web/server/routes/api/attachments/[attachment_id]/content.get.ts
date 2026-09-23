import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { requireAttachmentAccess } from '../../../../utils/attachmentAccess'
import { attachmentServiceFetch } from '../../../../utils/attachmentService'

export default defineHandler(async (event) => {
  const id = getRouterParam(event, 'attachment_id') || ''
  await requireAttachmentAccess(event, id)
  const response = await attachmentServiceFetch(`/v1/attachments/${id}/content`)
  if (!response.ok || !response.body) throw new HTTPError({ statusCode: response.status, statusMessage: 'attachment_content_unavailable' })
  return new Response(response.body, { status: response.status, headers: {
    'content-type': response.headers.get('content-type') || 'application/octet-stream',
    'content-disposition': response.headers.get('content-disposition') || 'inline',
    'cache-control': 'private, no-store'
  } })
})
