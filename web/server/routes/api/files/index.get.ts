import { defineHandler } from 'nitro'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq, or, desc } from '../../../utils/drizzle'

/**
 * GET /api/files
 * 获取当前用户可访问的文件列表（自己的文件 + shared 文件）。
 */
export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const userId = session.data.user?.id

  const db = useDrizzle()

  if (!userId) {
    // 未登录用户只能看 shared 文件
    return db.select()
      .from(tables.files)
      .where(eq(tables.files.visibility, 'shared'))
      .orderBy(desc(tables.files.createdAt))
  }

  // 登录用户：看自己的文件 + 所有 shared 文件
  return db.select()
    .from(tables.files)
    .where(
      or(
        eq(tables.files.userId, userId),
        eq(tables.files.visibility, 'shared')
      )
    )
    .orderBy(desc(tables.files.createdAt))
})
