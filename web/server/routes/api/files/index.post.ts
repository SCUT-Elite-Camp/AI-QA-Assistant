import { defineHandler, HTTPError } from 'nitro'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables } from '../../../utils/drizzle'
import { saveFile, guessMimeType } from '../../../utils/file-storage'
import { logAudit } from '../../../utils/audit-logger'
import { computeDocId, replaceFileGrants, type FileGrant } from '../../../utils/permission-service'
import { getRequestIP, getHeader, readMultipartFormData } from 'nitro/h3'

/**
 * POST /api/files
 * 上传文件。需要登录。
 *
 * 可选 multipart 字段：
 * - file: 文件本体（必填）
 * - visibility: 'private' | 'shared'（默认 private）
 * - grants: JSON 数组 [{ grantType: 'user'|'department'|'public', grantId: string|null }]
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

  const file = formData.find(p => p.name === 'file' && p.filename)
  if (!file || !file.filename || file.data.length === 0) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Invalid file' })
  }

  // 可见范围
  let visibility: 'private' | 'shared' = 'private'
  const visibilityPart = formData.find(p => p.name === 'visibility')
  if (visibilityPart) {
    const v = visibilityPart.data.toString().trim()
    if (v === 'private' || v === 'shared') visibility = v
  }

  // 授权记录
  let grants: FileGrant[] = []
  const grantsPart = formData.find(p => p.name === 'grants')
  if (grantsPart) {
    try {
      const parsed = JSON.parse(grantsPart.data.toString())
      if (Array.isArray(parsed)) {
        grants = parsed
          .map((g: any) => ({
            grantType: g?.grantType,
            grantId: g?.grantType === 'public' ? null : (g?.grantId ?? null),
          }))
          .filter((g: FileGrant) => ['user', 'department', 'public'].includes(g.grantType))
      }
    } catch {
      // 忽略非法 grants，按无授权处理
      grants = []
    }
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
    visibility,
    docId: computeDocId(storagePath),
  }).returning()

  if (!record) {
    throw new HTTPError({ statusCode: 500, statusMessage: 'Failed to save file record' })
  }

  // 写入权限授权记录
  if (grants.length > 0) {
    await replaceFileGrants(db, record.id, grants)
  }

  // 审计日志
  await logAudit({
    userId,
    action: 'file.upload',
    resourceType: 'file',
    resourceId: record.id,
    detail: { name: originalName, size: file.data.length, mimeType, visibility, grants },
    ip: getRequestIP(event) || undefined,
    userAgent: getHeader(event, 'user-agent') || undefined,
  })

  return record
})
