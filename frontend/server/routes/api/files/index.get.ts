import { defineHandler } from 'nitro'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq, or, desc, inArray } from '../../../utils/drizzle'
import { getGrantedFileIds, getFileGrants } from '../../../utils/permission-service'
import { isAdmin } from '../../../utils/admin'
import { syncKnowledgeBaseDocuments } from '../../../utils/knowledge-sync'

/**
 * GET /api/files
 * 获取当前用户可访问的文件列表（自己的文件 + shared 文件 + 授权文件）。
 * 附加权限信息：canManage（owner 或 admin）与 grants，以及 spaceKey。
 */
export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const userId = session.data.user?.id || 'dev-user'

  const db = useDrizzle()

  // 确保有知识库数据
  const existingCount = await db.select({ count: tables.files.id }).from(tables.files)
  if (existingCount.length === 0) {
    await syncKnowledgeBaseDocuments().catch(() => {})
  }

  const admin = userId ? await isAdmin(userId) : true

  let files: typeof tables.files.$inferSelect[]
  if (admin) {
    // 管理员查看全部文件
    files = await db.select()
      .from(tables.files)
      .orderBy(desc(tables.files.createdAt))
  }
  else {
    // 登录用户：自己的文件 + 所有 shared 文件 + 授权（public/用户/部门）文件
    const grantedFileIds = await getGrantedFileIds(db, userId)

    const conditions = [
      eq(tables.files.userId, userId),
      eq(tables.files.visibility, 'shared'),
    ]
    if (grantedFileIds.length > 0) {
      conditions.push(inArray(tables.files.id, grantedFileIds))
    }

    files = await db.select()
      .from(tables.files)
      .where(or(...conditions))
      .orderBy(desc(tables.files.createdAt))
  }

  const result = []
  for (const f of files) {
    const canManage = admin || f.userId === userId
    let grants: Array<{ grantType: string; grantId: string | null }> = []
    if (canManage) {
      const rows = await getFileGrants(db, f.id)
      grants = rows.map(r => ({ grantType: r.grantType, grantId: r.grantId }))
    }

    // 从 storagePath 中解析 Space Key
    let spaceKey = 'DEFAULT'
    if (f.storagePath?.startsWith('confluence://')) {
      const stripped = f.storagePath.replace('confluence://', '')
      spaceKey = stripped.split('/')[0] || 'RAG'
    }

    result.push({
      ...f,
      spaceKey,
      canManage,
      grants,
    })
  }

  return result
})
