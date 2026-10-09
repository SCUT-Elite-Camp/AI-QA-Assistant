import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam, readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { eq, tables, useDrizzle } from '../../../../utils/drizzle'
import { requireAttachmentAccess } from '../../../../utils/attachmentAccess'
import { requireCsrf, requireTopicRole } from '../../../../utils/attachmentAuth'
import { attachmentServiceJson } from '../../../../utils/attachmentService'
import { isAnonymousAttachmentPrincipal } from '../../../../../shared/utils/attachmentScope'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const id = getRouterParam(event, 'attachment_id') || ''
  const body = await readValidatedBody(event, z.object({ topic_id: z.string().min(1) }).parse)
  const { attachment, userId } = await requireAttachmentAccess(event, id)
  if (isAnonymousAttachmentPrincipal(userId)) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'anonymous_topic_attachment_forbidden' })
  }
  await requireTopicRole(event, body.topic_id, 'editor')
  if (attachment.ownerId !== userId || attachment.scope === 'topic') {
    throw new HTTPError({ statusCode: 403, statusMessage: 'attachment_promote_forbidden' })
  }
  if (!['ready', 'needs_review'].includes(attachment.status)) {
    throw new HTTPError({ statusCode: 409, statusMessage: 'attachment_not_ready' })
  }
  const remote = await attachmentServiceJson<any>(`/v1/attachments/${id}/scope`, {
    method: 'PATCH', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ scope: 'topic', expires_at: null, dedupe_domain: `topic:${body.topic_id}` })
  })
  await useDrizzle().update(tables.attachments).set({ scope: 'topic', topicId: body.topic_id, expiresAt: null }).where(eq(tables.attachments.id, id))
  return remote
})
