import { defineHandler } from 'nitro'
import { useDrizzle, tables } from '../../utils/drizzle'

export default defineHandler(async () => {
  const db = useDrizzle()
  const topics = await db.select().from(tables.topics)
  return topics.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime())
})


