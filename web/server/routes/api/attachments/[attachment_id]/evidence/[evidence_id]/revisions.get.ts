import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { requireAttachmentAccess } from '../../../../../../utils/attachmentAccess'
import { attachmentServiceJson } from '../../../../../../utils/attachmentService'

export default defineHandler(async (event) => {
  const attachmentId = getRouterParam(event, 'attachment_id') || ''
  const evidenceId = getRouterParam(event, 'evidence_id') || ''
  await requireAttachmentAccess(event, attachmentId)
  return attachmentServiceJson(`/v1/attachments/${attachmentId}/evidence/${evidenceId}/revisions`)
})
