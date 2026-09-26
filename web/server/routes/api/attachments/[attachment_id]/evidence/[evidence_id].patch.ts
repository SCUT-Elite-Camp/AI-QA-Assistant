import { defineHandler } from 'nitro'
import { getRouterParam, readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { requireAttachmentAccess } from '../../../../../utils/attachmentAccess'
import { requireCsrf } from '../../../../../utils/attachmentAuth'
import { attachmentServiceJson } from '../../../../../utils/attachmentService'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const attachmentId = getRouterParam(event, 'attachment_id') || ''
  const evidenceId = getRouterParam(event, 'evidence_id') || ''
  const { userId } = await requireAttachmentAccess(event, attachmentId, 'editor')
  const body = await readValidatedBody(event, z.object({
    expected_version: z.number().int().positive(),
    corrected_content: z.string().trim().min(1).max(200_000),
    reason: z.string().max(500).default('')
  }).parse)
  return attachmentServiceJson(`/v1/attachments/${attachmentId}/evidence/${evidenceId}`, {
    method: 'PATCH', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ...body, actor_id: userId })
  })
})
