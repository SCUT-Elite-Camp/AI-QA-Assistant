import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { deleteFile } from '../../../utils/file-storage'
import { logAudit } from '../../../utils/audit-logger'
import { requireFileAccess } from '../../../utils/permission-service'
import { getRequestIP, getHeader } from 'nitro/h3'

/**
 * DELETE /api/files/:id
 * 删除文件。仅文件所有者可删除自己的文件。
 */
export default defineHandler(async (event) => {
  const fileId = getRouterParam(event, 'id')
  if (!fileId) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Missing file id' })
  }

  const session = await useUserSession(event)
  const userId = session.data.user?.id

  const db = useDrizzle()

  // 统一的文件访问控制（仅 owner 可删除）
  const access = await requireFileAccess(db, userId, fileId, { mode: 'delete' })
  if (!access.ok || !access.file) {
    throw new HTTPError({ statusCode: access.statusCode, statusMessage: access.statusCode === 404 ? 'File not found' : access.statusCode === 401 ? 'Unauthorized' : 'Access denied: only owner can delete' })
  }
  const file = access.file

  // 删除磁盘文件
  await deleteFile(file.storagePath)

  // 删除数据库记录
  await db.delete(tables.files).where(eq(tables.files.id, fileId))

  // 审计日志
  await logAudit({
    userId,
    action: 'file.delete',
    resourceType: 'file',
    resourceId: file.id,
    detail: { name: file.originalName },
    ip: getRequestIP(event) || undefined,
    userAgent: getHeader(event, 'user-agent') || undefined,
  })

  return { success: true }
})
