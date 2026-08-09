import { defineHandler, HTTPError } from 'nitro'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables } from '../../../utils/drizzle'
import { saveFile, guessMimeType } from '../../../utils/file-storage'
import { logAudit } from '../../../utils/audit-logger'
import { getRequestIP, getHeader, readMultipartFormData } from 'nitro/h3'

/**
 * POST /api/files
 * 上传文件。需要登录。
 */
export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const userId = session.data.user?.id

  if (!userId) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Unauthorized' })
  }

  // 读取 multipart/form-data
  const formData = await readMultipartFormData(event)
  if (!formData || formData.length === 0) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'No file uploaded' })
  }

  const file = formData[0]
  if (!file || !file.filename || file.data.length === 0) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Invalid file' })
  }

  const originalName = file.filename
  const mimeType = file.type || guessMimeType(originalName)
  const storagePath = await saveFile(Buffer.from(file.data), originalName)

  const db = useDrizzle()
  const [record] = await db.insert(tables.files).values({
    userId,
    name: originalName,
    originalName,
    mimeType,
    size: file.data.length,
    storagePath,
    visibility: 'private',
  }).returning()

  if (!record) {
    throw new HTTPError({ statusCode: 500, statusMessage: 'Failed to save file record' })
  }

  // 审计日志
  await logAudit({
    userId,
    action: 'file.upload',
    resourceType: 'file',
    resourceId: record.id,
    detail: { name: originalName, size: file.data.length, mimeType },
    ip: getRequestIP(event) || undefined,
    userAgent: getHeader(event, 'user-agent') || undefined,
  })

  return record
})
