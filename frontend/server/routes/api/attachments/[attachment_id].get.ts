import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { eq, tables, useDrizzle } from '../../../utils/drizzle'
import { requireAttachmentAccess } from '../../../utils/attachmentAccess'
import { attachmentServiceJson } from '../../../utils/attachmentService'

export default defineHandler(async (event) => {
  const id = getRouterParam(event, 'attachment_id') || ''
  const { attachment } = await requireAttachmentAccess(event, id)
  const remote = await attachmentServiceJson<any>(`/v1/attachments/${id}`)
  await useDrizzle().update(tables.attachments).set({
    status: remote.status,
    visionStatus: remote.vision_status,
    evidenceVersion: remote.evidence_version,
    errorCode: remote.error_code || ''
  }).where(eq(tables.attachments.id, id))
  return { ...attachment, ...remote, blob_path: undefined, key_id: undefined }
})
