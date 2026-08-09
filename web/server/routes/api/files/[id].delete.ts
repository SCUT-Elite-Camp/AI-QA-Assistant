import { defineHandler, HTTPError, getRouterParam } from 'nitro'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { deleteFile } from '../../../utils/file-storage'
import { logAudit } from '../../../utils/audit-logger'
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

  if (!userId) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Unauthorized' })
  }

  const db = useDrizzle()
  const [file] = await db.select().from(tables.files).where(eq(tables.files.id, fileId))

  if (!file) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'File not found' })
  }

  if (file.userId !== userId) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'Access denied: only owner can delete' })
  }

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
