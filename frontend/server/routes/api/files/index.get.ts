import { defineHandler } from 'nitro'
import { useUserSession } from '../../../utils/session'
import { useDrizzle, tables, eq, or, desc, inArray } from '../../../utils/drizzle'
import { getGrantedFileIds, getFileGrants } from '../../../utils/permission-service'
import { isAdmin } from '../../../utils/admin'

/**
 * GET /api/files
 * 获取当前用户可访问的文件列表（自己的文件 + shared 文件 + 授权文件）。
 * 附加权限信息：canManage（owner 或 admin）与 grants（仅 canManage 时返回，避免泄露授权细节）。
 */
export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const userId = session.data.user?.id

  const db = useDrizzle()

  let files: typeof tables.files.$inferSelect[]
  if (!userId) {
    // 未登录用户只能看 shared 文件
    files = await db.select()
      .from(tables.files)
      .where(eq(tables.files.visibility, 'shared'))
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

  const admin = userId ? await isAdmin(userId) : false

  const result = []
  for (const f of files) {
    const canManage = admin || f.userId === userId
    let grants: Array<{ grantType: string; grantId: string | null }> = []
    if (canManage) {
      const rows = await getFileGrants(db, f.id)
      grants = rows.map(r => ({ grantType: r.grantType, grantId: r.grantId }))
    }
    result.push({
      ...f,
      canManage,
      grants,
    })
  }

  return result
})
