import { defineHandler } from 'nitro'
import { getQuery } from 'nitro/h3'
import { useUserSession } from '../../utils/session'
import { useDrizzle, tables, eq, and, desc, sql } from '../../utils/drizzle'

/**
 * GET /api/audit-logs?limit=50&resourceType=file&action=file.download
 * 查询审计日志。仅返回当前用户的审计记录。
 */
export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const userId = session.data.user?.id

  const query = getQuery(event)
  const limit = Math.min(Number(query.limit) || 50, 200)
  const resourceType = query.resourceType as string | undefined
  const action = query.action as string | undefined

  const db = useDrizzle()

  // 未登录：只能看匿名审计
  if (!userId) {
    return db.select()
      .from(tables.auditLogs)
      .where(sql`${tables.auditLogs.userId} IS NULL`)
      .orderBy(desc(tables.auditLogs.createdAt))
      .limit(limit)
  }

  // 构建动态条件
  const conditions = [eq(tables.auditLogs.userId, userId)]
  if (resourceType) conditions.push(eq(tables.auditLogs.resourceType, resourceType))
  if (action) conditions.push(eq(tables.auditLogs.action, action))

  return db.select()
    .from(tables.auditLogs)
    .where(and(...conditions))
    .orderBy(desc(tables.auditLogs.createdAt))
    .limit(limit)
})
