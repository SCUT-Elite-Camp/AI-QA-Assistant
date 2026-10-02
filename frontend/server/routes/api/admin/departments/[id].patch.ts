import { defineHandler, HTTPError } from 'nitro'
import { getRouterParam } from 'nitro/h3'
import { readValidatedBody } from 'nitro/h3'
import { z } from 'zod'
import { useDrizzle, tables, eq } from '../../../../utils/drizzle'
import { requireAdmin } from '../../../../utils/admin'

const updateDepartmentSchema = z.object({
  name: z.string().min(1).optional(),
  parentId: z.string().nullable().optional(),
})

/**
 * PATCH /api/admin/departments/:id
 * 编辑部门（重命名或调整上级部门）。仅管理员可访问。
 */
export default defineHandler(async (event) => {
  await requireAdmin(event)

  const departmentId = getRouterParam(event, 'id')
  if (!departmentId) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Missing department id' })
  }

  const body = await readValidatedBody(event, updateDepartmentSchema.parse)
  const db = useDrizzle()

  const [department] = await db
    .select()
    .from(tables.departments)
    .where(eq(tables.departments.id, departmentId))

  if (!department) {
    throw new HTTPError({ statusCode: 404, statusMessage: 'Department not found' })
  }

  // 禁止把部门设置成自己的子部门（防环）
  if (body.parentId && body.parentId === departmentId) {
    throw new HTTPError({ statusCode: 400, statusMessage: 'Department cannot be its own parent' })
  }

  const patch: Record<string, unknown> = {}
  if (body.name !== undefined) patch.name = body.name
  if (body.parentId !== undefined) patch.parentId = body.parentId

  if (Object.keys(patch).length > 0) {
    await db.update(tables.departments).set(patch).where(eq(tables.departments.id, departmentId))
  }

  return { success: true }
})
