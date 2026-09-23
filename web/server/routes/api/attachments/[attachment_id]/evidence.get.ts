import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { requireAttachmentAccess } from '../../../../utils/attachmentAccess'
import { attachmentServiceJson } from '../../../../utils/attachmentService'

export default defineHandler(async (event) => {
  const id = getRouterParam(event, 'attachment_id') || ''
  await requireAttachmentAccess(event, id)
  return attachmentServiceJson(`/v1/attachments/${id}/evidence`)
})
