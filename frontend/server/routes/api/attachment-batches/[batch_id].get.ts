import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { and, eq, tables, useDrizzle } from '../../../utils/drizzle'
import { requirePrincipal, requireTopicRole } from '../../../utils/attachmentAuth'
import { attachmentBatchExpired } from '../../../../shared/utils/attachmentScope'

export default defineHandler(async (event) => {
  const userId = await requirePrincipal(event)
  const batchId = getRouterParam(event, 'batch_id') || ''
  const db = useDrizzle()
  const batch = await db.query.attachmentBatches.findFirst({ where: and(eq(tables.attachmentBatches.id, batchId), eq(tables.attachmentBatches.ownerId, userId)) })
  if (!batch) throw new HTTPError({ statusCode: 404, statusMessage: 'batch_not_found' })
  if (batch.topicId) await requireTopicRole(event, batch.topicId, 'viewer')
  if (attachmentBatchExpired(batch.expiresAt)) {
    throw new HTTPError({ statusCode: 410, statusMessage: 'batch_expired' })
  }
  const attachments = await db.query.attachments.findMany({ where: eq(tables.attachments.batchId, batch.id) })
  return { ...batch, attachments }
})
