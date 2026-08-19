import { HTTPError } from 'nitro'
import type { HTTPEvent } from 'nitro/h3'
import { eq, tables, useDrizzle } from './drizzle'
import { requirePrincipal, requireTopicRole, type TopicRole } from './attachmentAuth'

export function attachmentHasExpired(attachment: { scope: string, expiresAt: Date | null }, now = new Date()): boolean {
  return attachment.scope !== 'topic' && !!attachment.expiresAt && attachment.expiresAt.getTime() <= now.getTime()
}

export async function requireAttachmentAccess(event: HTTPEvent, attachmentId: string, minimumTopicRole: TopicRole = 'viewer') {
  const db = useDrizzle()
  const attachment = await db.query.attachments.findFirst({ where: eq(tables.attachments.id, attachmentId) })
  if (!attachment || attachment.deletedAt) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'attachment_not_found' })
  }
  if (attachmentHasExpired(attachment)) {
    await db.update(tables.attachments).set({ status: 'expired' }).where(eq(tables.attachments.id, attachmentId))
    throw new HTTPError({ statusCode: 404, statusMessage: 'attachment_expired' })
  }
  const userId = await requirePrincipal(event)
  let topicRole: TopicRole | null = null
  if (attachment.topicId) {
    topicRole = (await requireTopicRole(event, attachment.topicId, minimumTopicRole)).role
  } else if (attachment.ownerId !== userId) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'attachment_forbidden' })
  }
  return { attachment, userId, topicRole }
}
