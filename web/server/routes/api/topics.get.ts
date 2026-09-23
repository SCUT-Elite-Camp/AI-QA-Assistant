import { defineHandler } from 'nitro'
import { inArray, useDrizzle, tables, eq } from '../../utils/drizzle'
import { requirePrincipal } from '../../utils/attachmentAuth'

export default defineHandler(async (event) => {
  const userId = await requirePrincipal(event)
  const db = useDrizzle()
  const memberships = await db.query.topicMembers.findMany({ where: eq(tables.topicMembers.userId, userId) })
  if (!memberships.length) return []
  const topics = await db.select().from(tables.topics).where(inArray(tables.topics.id, memberships.map(member => member.topicId)))
  return topics.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime())
})


