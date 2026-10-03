import { defineHandler } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { asc, eq, inArray, tables, useDrizzle } from '../../../../utils/drizzle'
import { requireTopicRole } from '../../../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  const topicId = getRouterParam(event, 'id') || ''
  await requireTopicRole(event, topicId, 'viewer')
  const db = useDrizzle()
  const items = await db.query.topicMembers.findMany({
    where: eq(tables.topicMembers.topicId, topicId),
    orderBy: [asc(tables.topicMembers.createdAt)]
  })
  const users = items.length
    ? await db.query.users.findMany({ where: inArray(tables.users.id, items.map(item => item.userId)) })
    : []
  const byId = new Map(users.map(user => [user.id, user]))
  return { items: items.map(item => ({
    ...item,
    name: byId.get(item.userId)?.name || '',
    email: byId.get(item.userId)?.email || '',
    username: byId.get(item.userId)?.username || '',
  })) }
})
