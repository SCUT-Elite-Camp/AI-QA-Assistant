import { z } from 'zod'
import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { and, eq, tables, useDrizzle } from '../../../../../utils/drizzle'
import { ensureOwnerContinuity, requireCsrf, requireTopicRole } from '../../../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const topicId = getRouterParam(event, 'id') || ''
  const userId = z.string().min(1).max(200).parse(getRouterParam(event, 'user_id'))
  await requireTopicRole(event, topicId, 'owner')
  const db = useDrizzle()
  const member = await db.query.topicMembers.findFirst({
    where: and(eq(tables.topicMembers.topicId, topicId), eq(tables.topicMembers.userId, userId))
  })
  if (!member) return { deleted: false }
  if (member.role === 'owner') {
    const owners = await db.query.topicMembers.findMany({
      where: and(eq(tables.topicMembers.topicId, topicId), eq(tables.topicMembers.role, 'owner'))
    })
    ensureOwnerContinuity(member.role, undefined, owners.length)
  }
  await db.delete(tables.topicMembers).where(
    and(eq(tables.topicMembers.topicId, topicId), eq(tables.topicMembers.userId, userId))
  )
  return { deleted: true }
})
