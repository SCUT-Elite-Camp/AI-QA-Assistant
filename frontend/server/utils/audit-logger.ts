import { useDrizzle, tables } from './drizzle'

/**
 * 记录审计日志。
 *
 * @param userId    操作用户 ID（可空，如匿名操作）
 * @param action    操作类型 (e.g. 'file.view', 'file.download', 'file.delete', 'file.upload')
 * @param resourceType 资源类型 (e.g. 'file', 'chat')
 * @param resourceId   资源 ID
 * @param detail    额外上下文 (JSON)
 * @param ip        请求 IP
 * @param userAgent 浏览器 UA
 */
export async function logAudit(params: {
  userId?: string | null
  action: string
  resourceType: string
  resourceId?: string
  detail?: Record<string, unknown>
  ip?: string
  userAgent?: string
}) {
  const db = useDrizzle()
  await db.insert(tables.auditLogs).values({
    userId: params.userId || null,
    action: params.action,
    resourceType: params.resourceType,
    resourceId: params.resourceId || null,
    detail: params.detail || null,
    ip: params.ip || null,
    userAgent: params.userAgent || null,
  })
}
