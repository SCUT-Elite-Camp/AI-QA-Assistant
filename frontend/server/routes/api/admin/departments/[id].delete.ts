import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { useDrizzle, tables, eq, inArray } from '../../../../utils/drizzle'
import { requireAdmin } from '../../../../utils/admin'

/**
 * DELETE /api/admin/departments/:id
 * 删除部门。子部门会被提升为顶级部门，用户-部门关联被级联删除。仅管理员可访问。
 */
export default defineHandler(async (event) => {
  await requireAdmin(event)

  const departmentId = getRouterParam(event, 'id')
  if (!departmentId) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Missing department id' })
  }

  const db = useDrizzle()

  const [department] = await db
    .select()
    .from(tables.departments)
    .where(eq(tables.departments.id, departmentId))

  if (!department) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Department not found' })
  }

  // 将子部门提升为顶级部门
  const children = await db
    .select()
    .from(tables.departments)
    .where(eq(tables.departments.parentId, departmentId))

  if (children.length > 0) {
    await db
      .update(tables.departments)
      .set({ parentId: null })
      .where(inArray(tables.departments.id, children.map(c => c.id)))
  }

  // 删除部门（user_departments / file_permissions 通过外键级联清理）
  await db.delete(tables.departments).where(eq(tables.departments.id, departmentId))

  return { success: true }
})
