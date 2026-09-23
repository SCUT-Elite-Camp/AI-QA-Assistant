import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { requireAttachmentAccess } from '../../../../utils/attachmentAccess'
import { requireCsrf } from '../../../../utils/attachmentAuth'
import { attachmentServiceJson } from '../../../../utils/attachmentService'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const id = getRouterParam(event, 'attachment_id') || ''
  await requireAttachmentAccess(event, id, 'editor')
  return attachmentServiceJson(`/v1/attachments/${id}/retry`, { method: 'POST' })
})
