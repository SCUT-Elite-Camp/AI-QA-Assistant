import { defineHandler } from 'nitro'
import { useDrizzle, tables, asc } from '../../../../utils/drizzle'
import { requireAdmin } from '../../../../utils/admin'

/**
 * GET /api/admin/departments
 * 获取部门列表（平铺，含 parentId 与用户数），前端据此组装层级树。仅管理员可访问。
 */
export default defineHandler(async (event) => {
  await requireAdmin(event)
  const db = useDrizzle()

  const departments = await db
    .select()
    .from(tables.departments)
    .orderBy(asc(tables.departments.name))

  const memberships = await db.select().from(tables.userDepartments)
  const userCount = new Map<string, number>()
  for (const m of memberships) {
    userCount.set(m.departmentId, (userCount.get(m.departmentId) ?? 0) + 1)
  }

  return departments.map(d => ({
    id: d.id,
    name: d.name,
    parentId: d.parentId,
    userCount: userCount.get(d.id) ?? 0,
    createdAt: d.createdAt,
  }))
})
