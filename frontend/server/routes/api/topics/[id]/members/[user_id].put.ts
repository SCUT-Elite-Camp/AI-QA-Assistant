import { z } from 'zod'
import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam, readValidatedBody } from 'nitro/h3'
import { and, eq, or, tables, useDrizzle } from '../../../../../utils/drizzle'
import { ensureOwnerContinuity, requireCsrf, requireTopicRole } from '../../../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  requireCsrf(event)
  const topicId = getRouterParam(event, 'id') || ''
  const identifier = z.string().min(1).max(200).parse(getRouterParam(event, 'user_id'))
  const body = await readValidatedBody(event, z.object({ role: z.enum(['owner', 'editor', 'viewer']) }).parse)
  await requireTopicRole(event, topicId, 'owner')
  const db = useDrizzle()
  const user = await db.query.users.findFirst({
    where: or(
      eq(tables.users.id, identifier),
      eq(tables.users.email, identifier),
      eq(tables.users.username, identifier),
    )
  })
  if (!user) throw new HTTPError({ statusCode: 404, statusMessage: 'user_not_found' })
  const userId = user.id

  const existing = await db.query.topicMembers.findFirst({
    where: and(eq(tables.topicMembers.topicId, topicId), eq(tables.topicMembers.userId, userId))
  })
  if (existing?.role === 'owner' && body.role !== 'owner') {
    const owners = await db.query.topicMembers.findMany({
      where: and(eq(tables.topicMembers.topicId, topicId), eq(tables.topicMembers.role, 'owner'))
    })
    ensureOwnerContinuity(existing.role, body.role, owners.length)
  }
  await db.insert(tables.topicMembers).values({ topicId, userId, role: body.role })
    .onConflictDoUpdate({
      target: [tables.topicMembers.topicId, tables.topicMembers.userId],
      set: { role: body.role }
    })
  return { topic_id: topicId, user_id: userId, role: body.role }
})
