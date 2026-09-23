import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { and, eq, tables, useDrizzle } from '../../../../utils/drizzle'
import { requireTopicRole } from '../../../../utils/attachmentAuth'
import { attachmentServiceJson } from '../../../../utils/attachmentService'

export default defineHandler(async (event) => {
  const topicId = getRouterParam(event, 'id') || ''
  const access = await requireTopicRole(event, topicId, 'viewer')
  const db = useDrizzle()
  const items = await db.query.attachments.findMany({
    where: and(eq(tables.attachments.topicId, topicId), eq(tables.attachments.scope, 'topic'))
  })
  const visible = items.filter(item => !item.deletedAt)
  const refreshed = await Promise.all(visible.map(async item => {
    if (!['uploading', 'scanning', 'parsing'].includes(item.status)) return item
    const remote = await attachmentServiceJson<any>(`/v1/attachments/${item.id}`).catch(() => null)
    if (!remote) return item
    const values = {
      status: remote.status,
      visionStatus: remote.vision_status,
      evidenceVersion: remote.evidence_version,
      errorCode: remote.error_code || '',
    }
    await db.update(tables.attachments).set(values).where(eq(tables.attachments.id, item.id))
    return { ...item, ...values }
  }))
  return { items: refreshed, role: access.role, current_user_id: access.userId }
})
