import { defineHandler, HTTPError } from 'nitro'
import { getQuery, getRouterParam } from 'nitro/h3'
import { requireAttachmentAccess } from '../../../../utils/attachmentAccess'
import { attachmentServiceFetch, attachmentServiceJson } from '../../../../utils/attachmentService'

export default defineHandler(async (event) => {
  const attachmentId = getRouterParam(event, 'attachment_id') || ''
  await requireAttachmentAccess(event, attachmentId)
  const query = getQuery(event)
  const page = Number(query.page || 0)
  const metadata = await attachmentServiceJson<any>(`/v1/attachments/${attachmentId}`)
  const previews = Array.isArray(metadata.previews) ? metadata.previews : []
  const derivative = (
    (page > 0 ? previews.find((item: any) => item.kind === 'page' && Number(item.locator?.page) === page) : null)
    || previews.find((item: any) => item.kind === 'thumbnail')
    || previews[0]
  )
  if (!derivative?.id) throw new HTTPError({ statusCode: 404, statusMessage: 'preview_not_found' })
  const response = await attachmentServiceFetch(`/v1/attachments/${attachmentId}/previews/${derivative.id}`)
  if (!response.ok || !response.body) throw new HTTPError({ statusCode: response.status, statusMessage: 'preview_unavailable' })
  return new Response(response.body, { headers: {
    'content-type': response.headers.get('content-type') || 'image/webp',
    'cache-control': 'private, no-store',
  } })
})
