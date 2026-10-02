import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { eq, tables, useDrizzle } from '../../../utils/drizzle'
import { requireAttachmentAccess } from '../../../utils/attachmentAccess'
import { requireCsrf } from '../../../utils/attachmentAuth'
import { attachmentServiceFetch } from '../../../utils/attachmentService'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const id = getRouterParam(event, 'attachment_id') || ''
  const { attachment, userId, topicRole } = await requireAttachmentAccess(event, id, 'editor')
  if (!attachment.topicId && attachment.ownerId !== userId) throw new Error('attachment_forbidden')
  if (attachment.topicId && topicRole !== 'owner' && attachment.ownerId !== userId) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'attachment_delete_forbidden' })
  }
  const response = await attachmentServiceFetch(`/v1/attachments/${id}`, { method: 'DELETE' })
  if (!response.ok && response.status !== 404) throw new Error('attachment_delete_failed')
  await useDrizzle().update(tables.attachments).set({ status: 'deleted', deletedAt: new Date() }).where(eq(tables.attachments.id, id))
  return { deleted: true }
})
