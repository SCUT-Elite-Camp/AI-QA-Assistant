import { defineHandler } from 'nitro'
import { useDrizzle, tables, desc } from '../../../utils/drizzle'
import { requireAdmin } from '../../../utils/admin'

/**
 * GET /api/admin/permissions
 * 获取所有文件的权限配置（文件列表 + 各自的授权记录）。仅管理员可访问。
 */
export default defineHandler(async (event) => {
  await requireAdmin(event)
  const db = useDrizzle()

  const files = await db.select().from(tables.files).orderBy(desc(tables.files.createdAt))
  const grants = await db.select().from(tables.filePermissions)

  const grantsByFile = new Map<string, Array<{ grantType: string; grantId: string | null }>>()
  for (const g of grants) {
    const list = grantsByFile.get(g.fileId) ?? []
    list.push({ grantType: g.grantType, grantId: g.grantId })
    grantsByFile.set(g.fileId, list)
  }

  return files.map(f => ({
    fileId: f.id,
    name: f.originalName,
    ownerId: f.userId,
    visibility: f.visibility,
    docId: f.docId,
    grants: grantsByFile.get(f.id) ?? [],
  }))
})
