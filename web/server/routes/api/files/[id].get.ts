import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { setHeader } from 'h3'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq } from '../../../utils/drizzle'
import { readFile } from '../../../utils/file-storage'
import { logAudit } from '../../../utils/audit-logger'
import { canAccessFile } from '../../../utils/permission-service'
import { getRequestIP, getHeader, getQuery } from 'nitro/h3'

/**
 * GET /api/files/:id
 * 查看或下载文件。需要 `?download=1` 参数触发下载。
 *
 * 访问控制：
 * - 文件所有者：可访问
 * - shared 文件：任何人可访问
 * - public / 指定用户 / 指定部门 授权：可访问
 * - 其他 private 文件：不可访问
 */
export default defineHandler(async (event) => {
  const fileId = getRouterParam(event, 'id')
  if (!fileId) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Missing file id' })
  }

  const session = await useUserSession(event)
  const userId = session.data.user?.id
  const db = useDrizzle()

  const [file] = await db.select().from(tables.files).where(eq(tables.files.id, fileId))

  if (!file) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'File not found' })
  }

  // 访问控制（owner / shared / public / 显式用户授权 / 部门授权）
  if (!(await canAccessFile(db, userId, file.id))) {
    throw new HTTPError({ statusCode: 403, statusMessage: 'Access denied' })
  }

  // 审计日志
  await logAudit({
    userId: userId || null,
    action: 'file.view',
    resourceType: 'file',
    resourceId: file.id,
    detail: { name: file.originalName },
    ip: getRequestIP(event) || undefined,
    userAgent: getHeader(event, 'user-agent') || undefined,
  })

  // 读取文件
  const buffer = await readFile(file.storagePath)

  const isDownload = getQuery(event).download === '1'
  setHeader(event, 'Content-Type', file.mimeType)
  setHeader(event, 'Content-Length', buffer.length.toString())

  if (isDownload) {
    setHeader(event, 'Content-Disposition', `attachment; filename="${encodeURIComponent(file.originalName)}"`)
    // 下载也记录审计
    await logAudit({
      userId: userId || null,
      action: 'file.download',
      resourceType: 'file',
      resourceId: file.id,
      detail: { name: file.originalName },
      ip: getRequestIP(event) || undefined,
      userAgent: getHeader(event, 'user-agent') || undefined,
    })
  } else {
    setHeader(event, 'Content-Disposition', `inline; filename="${encodeURIComponent(file.originalName)}"`)
  }

  setHeader(event, 'Cache-Control', 'private, max-age=3600')
  return buffer
})
